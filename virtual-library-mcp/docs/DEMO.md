# Live Demo Script

A ~10-minute walkthrough that shows every MCP concept with the Virtual
Library server and the [mcp-client-learning](https://github.com/willtech3/mcp-client-learning)
client. Each step names the protocol feature on display.

## Setup (before the demo)

```bash
# Terminal 1 - server (this repo)
just db-seed && just dev-http

# Terminal 2 - client (sibling repo)
export ANTHROPIC_API_KEY=...   # for the sampling steps
```

For the OAuth variant, run against the Cloud Run deployment instead and
drop `--anonymous` — the browser sign-in IS the demo of the
authorization spec.

## The script

**1. Discovery — "the server describes itself"**

```bash
mcp-client tools --server http://127.0.0.1:8080/mcp --anonymous
```

Point out: real parameter schemas per tool (an LLM can call these
correctly without guessing), read-only/idempotent annotations, icons.

**2. Structured search — "tools return data, not just prose"**

```bash
mcp-client call search_catalog --args '{"genre": "Dystopian", "available_only": true}' \
  --server http://127.0.0.1:8080/mcp --anonymous
```

Point out: the `structured` panel matches the tool's published
outputSchema. Try `{"query": "dune"}` too — it's a real catalog.

**3. Resources — "read-only data with URIs"**

```bash
mcp-client read "library://stats/popular/365/5" --server http://127.0.0.1:8080/mcp --anonymous
```

Point out: *Atomic Habits* and *Fahrenheit 451* top the charts because
the seeded circulation actually borrowed them more — stats derive from
records, nothing is hard-coded.

**4. Elicitation — "the server asks YOU mid-tool-call"**

```bash
mcp-client call renew_membership --args '{"patron_id": "patron_00002"}' \
  --server http://127.0.0.1:8080/mcp --anonymous
```

The terminal prompts for a renewal term (enum elicitation, SEP-1330).
Then show the approval variant: pick a patron with outstanding fines
(read `library://patrons/by-status/active` and look for
`outstanding_fines > 0`), check out any available book for them, and
decline the confirmation — the checkout aborts cleanly.

**5. Sampling — "the server borrows YOUR Claude"**

```bash
mcp-client call generate_book_insights \
  --args '{"isbn": "<isbn from step 2>", "insight_type": "summary"}' \
  --server http://127.0.0.1:8080/mcp --anonymous
```

The client shows the sampling request and asks permission — the human
controls the spend. Then run `insight_type: "similar_books"`: that one
hands Claude a catalog-search tool (SEP-1577), so its recommendations
cite books this library actually holds.

**6. Progress — "long operations stream status"**

```bash
mcp-client call bulk_import_books --args '{"file_path": "samples/books_medium.csv"}' \
  --server http://127.0.0.1:8080/mcp --anonymous
```

140 real books import with batch-by-batch progress and an ETA.

**7. Notifications + tasks — "the catalog goes into maintenance mode"**

```bash
mcp-client call regenerate_catalog --server http://127.0.0.1:8080/mcp --anonymous
```

Point out: progress across four stages, and the recommendations resource
disappears/reappears (`resources/list_changed`) during the rebuild. The
tool is also task-capable (SEP-1686) for clients that poll.

**Or run it all at once:**

```bash
mcp-client demo --server http://127.0.0.1:8080/mcp --anonymous
```

## Talking points if asked

- **Why is HTTP stateful?** Sampling/elicitation are server→client
  requests; they need a session stream. That's why Cloud Run runs with
  session affinity.
- **Where's the auth?** OAuth 2.1 + PKCE per the MCP authorization spec;
  the client implements discovery → registration → PKCE from scratch
  (`mcp_client/oauth.py` in the sibling repo is heavily annotated).
- **Is the data real?** 201 real authors, 393 real books, simulated
  circulation with verified invariants (`tests/test_seed_data.py`).
