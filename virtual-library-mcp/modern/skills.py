"""
Skills over MCP — the ``io.modelcontextprotocol/skills`` extension (SEP-2640).

Skills are the newest answer to an old question: how does a server teach an
agent to use it WELL?  Tool descriptions explain one call at a time;
``instructions`` is a single blob.  A *skill* is a directory of markdown
(plus supporting files) following the Agent Skills specification
(https://agentskills.io/specification): a ``SKILL.md`` with YAML frontmatter
(``name`` + ``description``) and a body the host loads only when the skill is
activated — progressive disclosure, so idle skills cost ~100 tokens of
metadata instead of thousands.

The MCP binding (SEP-2640, an Extensions Track SEP from the Skills Over MCP
Working Group) is deliberately boring, and that is the lesson: skills are NOT
a new primitive.  A competing proposal (SEP-2076, ``skills/list`` +
``skills/get``) was rejected because flattening skills to name-addressed
blobs loses the directory model.  Instead, SEP-2640 is *a convention over the
existing Resources primitive* plus exactly one new method:

- Every file of every skill is an ordinary resource under
  ``skill://<skill-path>/<file-path>``, readable via plain ``resources/read``.
  Per RFC 3986 the first path segment sits in the authority position but has
  NO network semantics — clients MUST NOT resolve it via DNS.
- The well-known resource ``skill://index.json`` enumerates skills.  Each
  entry carries the SKILL.md ``url``, a ``digest`` (``sha256:`` + 64 lowercase
  hex of the SKILL.md raw bytes), and a VERBATIM copy of the frontmatter
  rendered as JSON.  Hosts MUST verify both digest and frontmatter on load —
  a mismatch means the index and the content disagree, and the skill MUST NOT
  be used.  (The digest is same-origin and unsigned: it proves consistency,
  never trust.)
- ``resources/directory/read`` — the one new JSON-RPC method — lists the
  direct children of a *directory resource* (``mimeType: "inode/directory"``,
  URI written WITHOUT a trailing slash).  It is non-recursive by design:
  clients descend by re-calling on child directories, exactly like ``ls``.
  Gated behind the ``directoryRead: true`` capability setting; clients MUST
  NOT call it against a server that did not declare it.

Unknown or non-directory URIs error with ``-32602`` Invalid params — the same
code ``resources/read`` uses for unknown resources in MCP 2026-07-28 (which
retired the legacy ``-32002`` resource-not-found code).

An earlier revision of the SEP shipped skills as tar/zip archives; Core
Maintainers removed that (decompression bombs, path traversal, two retrieval
forms).  Files are always individually addressable resources — and because a
URI path maps onto OUR filesystem, this module treats path traversal as the
primary threat: every read resolves the target and verifies containment
under the skills root before touching bytes.

Wire shapes per research: SEP-2640 (PR modelcontextprotocol#2640, branch
``sep/skills-extension``) and https://agentskills.io/specification.
"""

import hashlib
import json
import mimetypes
import re
from base64 import b64encode
from pathlib import Path
from typing import Any

import yaml

from modern.errors import InvalidParamsError
from modern.types import (
    Annotations,
    BlobResourceContents,
    Resource,
    TextResourceContents,
)

# ---------------------------------------------------------------------------
# Constants from SEP-2640 / agentskills.io
# ---------------------------------------------------------------------------

#: Extension identifier — official ``io.modelcontextprotocol`` vendor prefix
#: per the extensions framework (SEP-2133).
SKILLS_EXTENSION_ID = "io.modelcontextprotocol/skills"

#: The well-known enumeration resource.  Reserved by construction: skill
#: names may only contain lowercase letters, digits, and hyphens, so
#: "index.json" can never collide with a skill path segment.
INDEX_URI = "skill://index.json"

URI_SCHEME_PREFIX = "skill://"

#: agentskills.io naming rule: 1-64 chars, lowercase alphanumerics and
#: hyphens, no leading/trailing hyphen, no consecutive hyphens.  The
#: "groups of [a-z0-9]+ joined by single hyphens" regex encodes all of that
#: except the length cap, which we check separately.
_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_NAME_MAX_LEN = 64
_DESCRIPTION_MAX_LEN = 1024

#: MIME types by extension.  ``mimetypes`` covers the common cases but is
#: platform-dependent and predates markdown ubiquity, so we pin the types a
#: skill directory actually contains.  SKILL.md SHOULD be text/markdown per
#: the SEP's resource-metadata guidance.
_MIME_OVERRIDES = {
    ".md": "text/markdown",
    ".json": "application/json",
    ".py": "text/x-python",
    ".sh": "text/x-shellscript",
    ".txt": "text/plain",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
}

#: Directory resources are identified by this MIME type (SEP-2640 §directory
#: resources) — the classic Unix value, not an invention of the SEP.
DIRECTORY_MIME_TYPE = "inode/directory"

#: WG annotations guidance (non-normative): SKILL.md files are meant for the
#: model, not for direct human display, and rank high among resources.
_SKILL_ANNOTATIONS = Annotations(audience=["assistant"], priority=0.8)


def _guess_mime_type(path: Path) -> str:
    """Content-appropriate mimeType for a skill file, by extension."""
    override = _MIME_OVERRIDES.get(path.suffix.lower())
    if override is not None:
        return override
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


# ---------------------------------------------------------------------------
# Frontmatter parsing (agentskills.io format)
# ---------------------------------------------------------------------------


def parse_frontmatter(text: str) -> dict[str, Any]:
    """Extract the YAML frontmatter object from SKILL.md text.

    Agent Skills format: the file MUST begin with a ``---`` fence line, the
    YAML document, and a closing ``---`` fence.  We return the parsed mapping
    VERBATIM — the index's ``frontmatter`` field must be "every field the
    author wrote, not a curated subset", and hosts verify it field-by-field
    against the file, so any normalization here would break verification.

    Raises:
        ValueError: the file has no frontmatter fences or the YAML between
            them is not a mapping.  This is a server-side content bug (bad
            skill authoring), not a protocol error, hence not an McpError.
    """
    if not text.startswith("---"):
        raise ValueError("SKILL.md must begin with a '---' YAML frontmatter fence")
    # Split on the first two fence lines only: '---' inside the body (a
    # markdown horizontal rule) must not truncate the document.
    parts = text.split("\n---", 2)
    if len(parts) < 2:
        raise ValueError("SKILL.md frontmatter is missing its closing '---' fence")
    yaml_source = parts[0].removeprefix("---")
    loaded = yaml.safe_load(yaml_source)
    if not isinstance(loaded, dict):
        # ValueError, not TypeError: the argument type was fine — the CONTENT
        # of the file is invalid per the agentskills.io format.
        raise ValueError("SKILL.md frontmatter must be a YAML mapping")  # noqa: TRY004
    return loaded


def _validate_frontmatter(frontmatter: dict[str, Any], dir_name: str) -> None:
    """Enforce the agentskills.io constraints SEP-2640 restates normatively.

    The critical rule is ``name`` == parent directory name: SEP-2640 requires
    the final ``<skill-path>`` URI segment to equal the frontmatter ``name``
    so hosts can recover the name from a URI without fetching frontmatter.
    Since we map URIs directly onto directories, dir name IS the URI segment.
    """
    name = frontmatter.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(name) or len(name) > _NAME_MAX_LEN:
        raise ValueError(
            f"Skill name {name!r} violates agentskills.io naming rules "
            "(1-64 chars, lowercase a-z/0-9/hyphens, no leading/trailing/"
            "consecutive hyphens)"
        )
    if name != dir_name:
        raise ValueError(
            f"Skill frontmatter name {name!r} must equal its directory name "
            f"{dir_name!r} (SEP-2640: the name must be recoverable from the URI)"
        )
    description = frontmatter.get("description")
    if not isinstance(description, str) or not 1 <= len(description) <= _DESCRIPTION_MAX_LEN:
        raise ValueError(
            f"Skill {name!r} description must be a 1-{_DESCRIPTION_MAX_LEN} character string"
        )


# ---------------------------------------------------------------------------
# SkillsProvider — the registry resource-provider for the skills namespace
# ---------------------------------------------------------------------------


class SkillsProvider:
    """Serves a directory tree of Agent Skills as ``skill://`` resources.

    Implements the registry provider contract (see modern/registry.py):

    - ``matches(uri)`` — claims the ``skill://`` namespace.
    - ``read(uri)`` — resource contents for any skill file, plus the
      generated ``skill://index.json``.
    - ``directory_read(uri)`` — direct children of a directory resource
      (the SEP-2640 ``resources/directory/read`` method body).
    - ``list_entries()`` — what this provider contributes to
      ``resources/list``: the index plus each SKILL.md.  Supporting files
      are deliberately NOT listed — they are addressable (the SEP requires
      un-listed skill URIs to be readable) but enumerating every reference
      file would bury the useful entries.  Clients browse via the index or
      directory reads instead.
    - ``capability_fragment()`` — merged into ServerCapabilities.extensions
      by the registry; declares ``directoryRead`` support.

    Skills are validated eagerly at construction (fail loud at startup on
    authoring mistakes), but index digests are recomputed from raw bytes on
    every read so the index can never drift from the content it attests to.
    """

    def __init__(self, root: Path) -> None:
        super().__init__()
        #: Resolved root — the containment boundary for every file access.
        #: resolve() pins symlinks and ".." now, so later comparisons are
        #: against a canonical path.
        self._root = root.resolve()
        if not self._root.is_dir():
            raise ValueError(f"Skills root {root} is not a directory")
        # Eager validation: scanning at startup surfaces bad frontmatter
        # immediately instead of at first client read.
        self._scan()

    # -- provider contract -------------------------------------------------

    def matches(self, uri: str) -> bool:
        """Does this provider own ``uri``?  (Everything under skill://.)"""
        return uri.startswith(URI_SCHEME_PREFIX)

    def capability_fragment(self) -> dict[str, dict[str, Any]]:
        """Extension capability advertised via server/discover.

        ``directoryRead: true`` is the extension's only setting; without it
        clients MUST NOT call resources/directory/read (SEP-2640 §4).
        """
        return {SKILLS_EXTENSION_ID: {"directoryRead": True}}

    def list_entries(self) -> list[Resource]:
        """Resources this provider adds to ``resources/list``.

        Per the SEP: the index MAY appear in resources/list (we choose to
        list it — discoverability is the point of a teaching server), and
        each SKILL.md carries name/description lifted from its frontmatter
        so hosts can surface skills without reading anything.
        """
        # NOTE: aliased fields (mimeType) are passed by their WIRE name —
        # pydantic accepts either, but the alias keeps static checkers happy.
        entries = [
            Resource(
                uri=INDEX_URI,
                name="index.json",
                description=(
                    "Well-known skills index (SEP-2640): url, digest, and "
                    "verbatim frontmatter for every skill on this server"
                ),
                mimeType="application/json",
                annotations=_SKILL_ANNOTATIONS,
            )
        ]
        for name, skill_dir in sorted(self._scan().items()):
            frontmatter = parse_frontmatter((skill_dir / "SKILL.md").read_text(encoding="utf-8"))
            entries.append(
                Resource(
                    uri=f"{URI_SCHEME_PREFIX}{name}/SKILL.md",
                    # SEP resource-metadata guidance: name from frontmatter
                    # (== final path segment), description from frontmatter.
                    name=name,
                    description=frontmatter["description"],
                    mimeType="text/markdown",
                    annotations=_SKILL_ANNOTATIONS,
                )
            )
        return entries

    async def read(self, uri: str) -> list[TextResourceContents | BlobResourceContents]:
        """``resources/read`` for the skills namespace.

        The index is generated; everything else is a file under the skills
        root, traversal-guarded.  Unknown URIs are ``-32602`` per the modern
        error mapping (the legacy -32002 resource-not-found is retired).
        """
        contents: list[TextResourceContents | BlobResourceContents]
        if uri == INDEX_URI:
            contents = [
                TextResourceContents(
                    uri=INDEX_URI,
                    mimeType="application/json",
                    text=json.dumps(self.build_index(), indent=2),
                )
            ]
            return contents

        path = self._resolve_uri(uri)
        if not path.is_file():
            raise InvalidParamsError(f"Resource not found: {uri}")

        data = path.read_bytes()
        mime_type = _guess_mime_type(path)
        try:
            # Text when the bytes say so — the wire distinguishes text
            # contents (raw string) from blob contents (base64), and hosts
            # render markdown/JSON far better as text.
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            contents = [
                BlobResourceContents(
                    uri=uri, mimeType=mime_type, blob=b64encode(data).decode("ascii")
                )
            ]
        else:
            contents = [TextResourceContents(uri=uri, mimeType=mime_type, text=text)]
        return contents

    async def directory_read(self, uri: str) -> list[Resource] | None:
        """``resources/directory/read`` (SEP-2640 §6) for the skills namespace.

        Returns None for URIs outside this provider's namespace so the
        registry can consult other providers; raises ``-32602`` for URIs
        inside the namespace that do not name a directory resource (unknown
        paths, plain files, trailing-slash spellings).

        The listing is one level deep by design — recursion is the client's
        loop, mirroring ``ls``.  Children are ordinary ``Resource`` entries;
        subdirectories are marked ``mimeType: "inode/directory"`` and are
        themselves valid targets for another directory read.
        """
        if not self.matches(uri):
            return None
        # Directory URIs are written WITHOUT a trailing slash (SEP-2640):
        # "skill://x/" and "skill://x" must not be two names for one thing.
        if uri.endswith("/"):
            raise InvalidParamsError(
                f"Not a directory resource: {uri} (directory URIs are written without a trailing slash)"
            )
        if uri == INDEX_URI:
            raise InvalidParamsError(f"Not a directory resource: {uri}")

        path = self._resolve_uri(uri)
        if not path.is_dir():
            raise InvalidParamsError(f"Not a directory resource: {uri}")

        children: list[Resource] = []
        # Sorted for determinism — the spec SHOULD for list ordering applies
        # in spirit here, and stable output makes caching/diffing sane.
        for child in sorted(path.iterdir(), key=lambda p: p.name):
            child_uri = f"{uri}/{child.name}"
            mime = DIRECTORY_MIME_TYPE if child.is_dir() else _guess_mime_type(child)
            children.append(Resource(uri=child_uri, name=child.name, mimeType=mime))
        return children

    # -- index generation ---------------------------------------------------

    def build_index(self) -> dict[str, Any]:
        """Build the ``skill://index.json`` document (SEP-2640 §3.1).

        All three entry fields are REQUIRED:

        - ``url``: the SKILL.md resource URI (final path segment == name).
        - ``digest``: ``sha256:`` + 64 lowercase hex over the SKILL.md RAW
          BYTES — not the parsed text, not a normalized form.  Hosts hash
          what ``resources/read`` hands them and compare; any transformation
          on our side would produce permanent verification failures.
        - ``frontmatter``: the author's YAML mapping rendered as JSON,
          verbatim.  Hosts compare it field-by-field against the fetched
          file's frontmatter, so this MUST come from the same parse rules.

        Recomputed from disk on every call: an index that attests stale
        digests is worse than no index (hosts MUST refuse mismatches).
        """
        skills: list[dict[str, Any]] = []
        for name, skill_dir in sorted(self._scan().items()):
            raw = (skill_dir / "SKILL.md").read_bytes()
            frontmatter = parse_frontmatter(raw.decode("utf-8"))
            skills.append(
                {
                    "url": f"{URI_SCHEME_PREFIX}{name}/SKILL.md",
                    "digest": f"sha256:{hashlib.sha256(raw).hexdigest()}",
                    "frontmatter": frontmatter,
                }
            )
        return {"skills": skills}

    # -- internals -----------------------------------------------------------

    def _scan(self) -> dict[str, Path]:
        """Find and validate every skill directory under the root.

        A skill is any direct child directory containing a SKILL.md.  This
        server uses single-segment skill paths (``skill://name/...``); the
        SEP also allows nested organizational prefixes, which we skip for
        clarity.  Validation raises ValueError — bad authoring should stop
        the server, not surface as per-request protocol errors.
        """
        skills: dict[str, Path] = {}
        for child in sorted(self._root.iterdir()):
            skill_md = child / "SKILL.md"
            if not child.is_dir() or not skill_md.is_file():
                continue
            frontmatter = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
            _validate_frontmatter(frontmatter, child.name)
            skills[child.name] = child
        return skills

    def _resolve_uri(self, uri: str) -> Path:
        """Map a ``skill://`` URI onto a filesystem path, safely.

        THE security-critical step of this module.  The URI path is
        attacker-controlled input that we are about to hand to the
        filesystem, so defense runs in two layers:

        1. Segment filter: reject empty, ``.``, ``..``, and backslash
           segments outright.  ``skill://../secrets`` dies here — dot
           segments have no legitimate meaning in skill URIs (relative
           references are resolved by the CLIENT against the skill root
           before they ever reach the wire).
        2. Containment check: resolve() the joined path (collapses any
           residue, follows symlinks) and verify the RESULT is still
           strictly inside the resolved skills root.  This catches what the
           filter cannot — e.g. a symlink inside the tree pointing outside.

        Failures report the same -32602 "Resource not found" as a missing
        file: telling an attacker "nice traversal attempt, that file
        exists" would be an information leak.
        """
        relative = uri[len(URI_SCHEME_PREFIX) :]
        segments = relative.split("/")
        if not relative or "\\" in relative or any(seg in ("", ".", "..") for seg in segments):
            raise InvalidParamsError(f"Resource not found: {uri}")
        candidate = self._root.joinpath(*segments).resolve()
        # Strict containment: the root itself is not a resource (the skills
        # NAMESPACE has no directory URI; skill roots and their
        # subdirectories do).
        if candidate == self._root or not candidate.is_relative_to(self._root):
            raise InvalidParamsError(f"Resource not found: {uri}")
        return candidate
