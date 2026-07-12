"""
Tests for modern/skills.py — the SEP-2640 skills extension provider.

These exercise the host-verifiable guarantees the SEP demands of servers:

- ``skill://index.json`` entries carry a correct ``sha256:<64hex>`` digest of
  the SKILL.md RAW BYTES and a VERBATIM copy of the YAML frontmatter — hosts
  MUST refuse skills whose fetched content disagrees with either, so we
  recompute both independently here, exactly as a host would;
- every file of every skill is readable via its ``skill://`` URI, with a
  content-appropriate mimeType;
- ``resources/directory/read`` semantics: non-recursive child listings,
  ``inode/directory`` markers on subdirectories, and ``-32602`` for anything
  that is not a directory resource (unknown paths, files, trailing slashes);
- path traversal (``skill://../...``) is rejected — URIs map onto OUR
  filesystem, so containment is the provider's core security duty;
- the capability fragment declares ``directoryRead`` under the reserved
  ``io.modelcontextprotocol/skills`` identifier.
"""

import hashlib
import json
from pathlib import Path

import pytest

from modern.errors import InvalidParamsError
from modern.skills import (
    DIRECTORY_MIME_TYPE,
    INDEX_URI,
    SKILLS_EXTENSION_ID,
    SkillsProvider,
    parse_frontmatter,
)
from modern.types import Resource, TextResourceContents

#: The real content shipped with the server: three library-domain skills.
SKILLS_ROOT = Path(__file__).parent.parent.parent / "skills"
EXPECTED_SKILLS = ("book-recommendations", "catalog-research", "circulation-policies")


@pytest.fixture
def provider() -> SkillsProvider:
    return SkillsProvider(SKILLS_ROOT)


async def read_index(provider: SkillsProvider) -> dict:
    contents = await provider.read(INDEX_URI)
    assert len(contents) == 1
    (content,) = contents
    assert isinstance(content, TextResourceContents)
    assert content.uri == INDEX_URI
    assert content.mime_type == "application/json"
    return json.loads(content.text)


# ---------------------------------------------------------------------------
# skill://index.json — digest and frontmatter verification (host obligations)
# ---------------------------------------------------------------------------


class TestIndex:
    async def test_index_lists_all_three_skills(self, provider):
        index = await read_index(provider)
        urls = [entry["url"] for entry in index["skills"]]
        assert urls == [f"skill://{name}/SKILL.md" for name in sorted(EXPECTED_SKILLS)]

    async def test_entries_carry_all_required_fields(self, provider):
        index = await read_index(provider)
        for entry in index["skills"]:
            assert set(entry) >= {"url", "digest", "frontmatter"}
            # name/description are always present in frontmatter, and the
            # final URI segment before SKILL.md MUST equal the name.
            assert entry["frontmatter"]["name"] == entry["url"].split("/")[-2]
            assert 1 <= len(entry["frontmatter"]["description"]) <= 1024

    async def test_digest_matches_recomputed_sha256_of_raw_bytes(self, provider):
        """The verification a host MUST perform: hash what resources/read
        returns and compare against the index digest."""
        index = await read_index(provider)
        for entry in index["skills"]:
            name = entry["frontmatter"]["name"]
            raw = (SKILLS_ROOT / name / "SKILL.md").read_bytes()
            expected = f"sha256:{hashlib.sha256(raw).hexdigest()}"
            assert entry["digest"] == expected

    async def test_digest_format_is_sha256_prefix_plus_64_lowercase_hex(self, provider):
        index = await read_index(provider)
        for entry in index["skills"]:
            scheme, _, hexdigest = entry["digest"].partition(":")
            assert scheme == "sha256"
            assert len(hexdigest) == 64
            assert hexdigest == hexdigest.lower()
            int(hexdigest, 16)  # every character is a hex digit

    async def test_frontmatter_is_verbatim_copy_of_skill_md_yaml(self, provider):
        """Field-by-field frontmatter comparison (SEP-2640 §3.2): any
        discrepancy between index and file is a verification failure."""
        index = await read_index(provider)
        for entry in index["skills"]:
            name = entry["frontmatter"]["name"]
            text = (SKILLS_ROOT / name / "SKILL.md").read_text(encoding="utf-8")
            assert entry["frontmatter"] == parse_frontmatter(text)

    async def test_read_via_index_url_round_trips_the_digest(self, provider):
        """End-to-end host flow: read the URL FROM the index, hash the
        returned text, verify against the index digest."""
        index = await read_index(provider)
        for entry in index["skills"]:
            (content,) = await provider.read(entry["url"])
            assert isinstance(content, TextResourceContents)
            digest = hashlib.sha256(content.text.encode("utf-8")).hexdigest()
            assert entry["digest"] == f"sha256:{digest}"


# ---------------------------------------------------------------------------
# resources/read across the whole namespace
# ---------------------------------------------------------------------------


class TestRead:
    async def test_every_file_of_every_skill_is_readable(self, provider):
        """The SEP baseline: a skill URI is directly readable whether or not
        it is indexed or listed."""
        files = [p for p in SKILLS_ROOT.rglob("*") if p.is_file()]
        assert len(files) >= 7  # 3 SKILL.md + 4 supporting files
        for path in files:
            uri = "skill://" + "/".join(path.relative_to(SKILLS_ROOT).parts)
            (content,) = await provider.read(uri)
            assert content.uri == uri
            assert isinstance(content, TextResourceContents)
            assert content.text == path.read_text(encoding="utf-8")

    async def test_skill_md_mime_type_is_markdown(self, provider):
        (content,) = await provider.read("skill://catalog-research/SKILL.md")
        assert content.mime_type == "text/markdown"

    async def test_skill_bodies_reference_real_server_features(self, provider):
        """Teaching-content sanity: skills must name actual tools/resources,
        not hallucinated ones."""
        (content,) = await provider.read("skill://book-recommendations/SKILL.md")
        assert isinstance(content, TextResourceContents)
        assert "search_catalog" in content.text
        assert "library://books/{isbn}" in content.text

    async def test_unknown_file_is_invalid_params(self, provider):
        with pytest.raises(InvalidParamsError):
            await provider.read("skill://book-recommendations/NOPE.md")

    async def test_unknown_skill_is_invalid_params(self, provider):
        with pytest.raises(InvalidParamsError):
            await provider.read("skill://no-such-skill/SKILL.md")

    async def test_matches_claims_only_the_skill_scheme(self, provider):
        assert provider.matches(INDEX_URI)
        assert provider.matches("skill://book-recommendations/SKILL.md")
        assert not provider.matches("library://books/list")


# ---------------------------------------------------------------------------
# Path traversal — the provider's core security duty
# ---------------------------------------------------------------------------


class TestTraversal:
    @pytest.mark.parametrize(
        "uri",
        [
            "skill://../secrets",
            "skill://../config.py",  # a real file one level above skills/
            "skill://book-recommendations/../../config.py",
            "skill://book-recommendations/..",
            "skill://./book-recommendations/SKILL.md",
            "skill://book-recommendations//SKILL.md",
            "skill://..%2F..",  # not decoded, but must still not resolve
            "skill://book-recommendations/..\\..\\secrets",
        ],
    )
    async def test_traversal_and_malformed_paths_rejected_on_read(self, provider, uri):
        with pytest.raises(InvalidParamsError):
            await provider.read(uri)

    async def test_traversal_rejected_on_directory_read(self, provider):
        with pytest.raises(InvalidParamsError):
            await provider.directory_read("skill://../..")

    async def test_escape_via_tmp_root(self, tmp_path):
        """Containment holds for an arbitrary root: a sibling secret outside
        the skills root is unreachable through any skill:// spelling."""
        root = tmp_path / "skills"
        skill = root / "demo"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\nbody\n")
        (tmp_path / "secret.txt").write_text("credentials")

        provider = SkillsProvider(root)
        for uri in ("skill://../secret.txt", "skill://demo/../../secret.txt"):
            with pytest.raises(InvalidParamsError):
                await provider.read(uri)


# ---------------------------------------------------------------------------
# resources/directory/read (SEP-2640 §6)
# ---------------------------------------------------------------------------


class TestDirectoryRead:
    async def test_skill_root_lists_direct_children_non_recursively(self, provider):
        resources = await provider.directory_read("skill://book-recommendations")
        assert resources is not None
        by_name = {r.name: r for r in resources}
        assert set(by_name) == {"SKILL.md", "references"}
        # Subdirectory: marked as a directory resource, NOT expanded inline.
        assert by_name["references"].mime_type == DIRECTORY_MIME_TYPE
        assert by_name["references"].uri == "skill://book-recommendations/references"
        assert by_name["SKILL.md"].mime_type == "text/markdown"
        # Non-recursive: the nested file never appears at this level.
        assert not any("GENRE_GUIDE" in r.uri for r in resources)

    async def test_nested_directory_read_descends_one_level(self, provider):
        resources = await provider.directory_read("skill://circulation-policies/references")
        assert resources is not None
        assert [r.name for r in resources] == ["FINES.md", "LOANS.md"]
        assert all(isinstance(r, Resource) for r in resources)
        assert all(r.mime_type == "text/markdown" for r in resources)
        assert resources[0].uri == "skill://circulation-policies/references/FINES.md"

    async def test_scripts_subdirectory(self, provider):
        resources = await provider.directory_read("skill://catalog-research/scripts")
        assert resources is not None
        assert [r.name for r in resources] == ["search_tips.md"]

    async def test_unknown_directory_is_invalid_params(self, provider):
        with pytest.raises(InvalidParamsError):
            await provider.directory_read("skill://book-recommendations/assets")

    async def test_file_uri_is_invalid_params(self, provider):
        """The method applies ONLY to directory resources — a file is -32602."""
        with pytest.raises(InvalidParamsError):
            await provider.directory_read("skill://book-recommendations/SKILL.md")

    async def test_trailing_slash_is_invalid_params(self, provider):
        """Directory URIs are written WITHOUT a trailing slash; the slashed
        spelling must not be a second name for the same resource."""
        with pytest.raises(InvalidParamsError):
            await provider.directory_read("skill://book-recommendations/")

    async def test_index_uri_is_not_a_directory(self, provider):
        with pytest.raises(InvalidParamsError):
            await provider.directory_read(INDEX_URI)

    async def test_foreign_scheme_returns_none_for_other_providers(self, provider):
        assert await provider.directory_read("library://books/list") is None

    async def test_empty_directory_returns_empty_list(self, tmp_path):
        root = tmp_path / "skills"
        skill = root / "demo"
        (skill / "empty").mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\nbody\n")
        provider = SkillsProvider(root)
        assert await provider.directory_read("skill://demo/empty") == []


# ---------------------------------------------------------------------------
# resources/list exposure + capability fragment
# ---------------------------------------------------------------------------


class TestListEntriesAndCapability:
    def test_capability_fragment_declares_directory_read(self, provider):
        assert provider.capability_fragment() == {SKILLS_EXTENSION_ID: {"directoryRead": True}}

    def test_list_entries_exposes_index_and_each_skill_md(self, provider):
        entries = provider.list_entries()
        uris = [e.uri for e in entries]
        assert uris[0] == INDEX_URI
        assert uris[1:] == [f"skill://{name}/SKILL.md" for name in sorted(EXPECTED_SKILLS)]
        # Supporting files are addressable but deliberately NOT listed.
        assert not any("references" in uri or "scripts" in uri for uri in uris)

    def test_skill_entries_carry_frontmatter_metadata_and_annotations(self, provider):
        entries = {e.uri: e for e in provider.list_entries()}
        for name in EXPECTED_SKILLS:
            entry = entries[f"skill://{name}/SKILL.md"]
            frontmatter = parse_frontmatter(
                (SKILLS_ROOT / name / "SKILL.md").read_text(encoding="utf-8")
            )
            # SEP resource-metadata guidance: name from frontmatter (== dir
            # segment), description from frontmatter, markdown mimeType.
            assert entry.name == name
            assert entry.description == frontmatter["description"]
            assert entry.mime_type == "text/markdown"
            # WG annotations guidance: assistant audience, high priority.
            assert entry.annotations is not None
            assert entry.annotations.audience == ["assistant"]
            assert entry.annotations.priority == 0.8


# ---------------------------------------------------------------------------
# Authoring validation — bad skills fail LOUD at construction
# ---------------------------------------------------------------------------


class TestValidation:
    def _make_skill(self, tmp_path: Path, dirname: str, frontmatter: str) -> Path:
        root = tmp_path / "skills"
        skill = root / dirname
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"---\n{frontmatter}\n---\nbody\n")
        return root

    def test_name_must_match_directory(self, tmp_path):
        root = self._make_skill(tmp_path, "some-dir", "name: other-name\ndescription: d")
        with pytest.raises(ValueError, match="must equal its directory name"):
            SkillsProvider(root)

    @pytest.mark.parametrize("bad_name", ["Bad-Name", "-lead", "trail-", "a--b", "has_underscore"])
    def test_name_must_satisfy_agentskills_rules(self, tmp_path, bad_name):
        root = self._make_skill(tmp_path, bad_name, f"name: {bad_name}\ndescription: d")
        with pytest.raises(ValueError, match="naming rules"):
            SkillsProvider(root)

    def test_description_is_required(self, tmp_path):
        root = self._make_skill(tmp_path, "demo", "name: demo")
        with pytest.raises(ValueError, match="description"):
            SkillsProvider(root)

    def test_missing_frontmatter_fence_is_rejected(self, tmp_path):
        root = tmp_path / "skills"
        (root / "demo").mkdir(parents=True)
        (root / "demo" / "SKILL.md").write_text("just a markdown body\n")
        with pytest.raises(ValueError, match="frontmatter"):
            SkillsProvider(root)

    def test_horizontal_rule_in_body_does_not_truncate_frontmatter(self):
        text = "---\nname: demo\ndescription: d\n---\nbody\n\n---\n\nmore body\n"
        assert parse_frontmatter(text) == {"name": "demo", "description": "d"}
