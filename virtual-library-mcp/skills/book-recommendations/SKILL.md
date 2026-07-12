---
name: book-recommendations
description: Recommend books to Virtual Library patrons using the server's catalog tools and resources. Use when a patron asks what to read next, wants titles similar to something they enjoyed, or needs suggestions filtered by genre, mood, or current availability. Covers grounding recommendations in patron history, verifying shelf availability, and following through with a checkout or hold.
license: MIT
metadata:
  author: virtual-library
  version: "1.0"
---

# Recommending Books from the Virtual Library

You are recommending from a REAL catalog with live availability, not from
general knowledge. Every title you suggest must exist in this library and
you should know whether it is on the shelf before you mention it.

## Workflow

### 1. Ground yourself in the patron's context (when you have a patron)

Read these resources before recommending:

- `library://patrons/{patron_id}/history` — what they have borrowed,
  returned, and rated. Never recommend a book they recently read unless
  they ask for a re-read.
- `library://recommendations/{patron_id}` — the server's precomputed
  personalized picks. Treat these as candidates to explain, not as a
  final answer.

Patron ids look like `patron_00042`. If you only have a name, ask for the
id or use `library://patrons/by-status/active` to locate the patron.

### 2. Find candidates in the catalog

Use the `search_catalog` tool. The arguments that matter most here:

- `genre` — exact genre name, case-insensitive (see
  `references/GENRE_GUIDE.md` for the vocabulary this catalog uses).
- `query` — full-text match across title, description, and ISBN.
- `available_only: true` — set this when the patron wants something to
  read *now*. Books with zero available copies can only be reserved.
- `sort_by: "publication_year"`, `sort_desc: true` — newest first, useful
  for "anything recent?".
- `page_size` — default 10, max 50. Fetch 20+ so you can filter.

For browsing whole shelves instead of searching, read
`library://books/by-genre/{genre}` or `library://books/by-author/{author_id}`.

### 3. Check what is popular (optional but persuasive)

`library://stats/popular/{days}/{limit}` ranks the most-borrowed books over
a window, e.g. `library://stats/popular/30/10` for the last month's top 10.
"Other patrons loved this" is a strong recommendation signal.

### 4. Enrich your top picks

For each finalist, call `generate_book_insights` with
`insight_type: "similar_books"` (or `"summary"` / `"themes"`) to produce
grounded blurbs. Verify details with `library://books/{isbn}` — it returns
the authoritative record including `available_copies`.

### 5. Present and follow through

Present 3–5 picks with a one-line reason tied to the patron's history or
stated mood. Then offer the next action:

- On the shelf → `checkout_book(patron_id, book_isbn)` (14-day loan).
- All copies out → `reserve_book(patron_id, book_isbn)` (hold expires in
  30 days by default).

The user-invocable prompt `recommend_books` (arguments: `genre`, `mood`,
`patron_id`, `limit`) packages steps 1–2 into a single template if the
client prefers prompt-driven flows.

## Pitfalls

- Do not recommend a title without checking availability; if it is checked
  out, say so and offer the hold instead.
- ISBNs in this catalog are 13 digits, no hyphens (e.g. `9780000000000`).
  `generate_book_insights` and `library://books/{isbn}` both require this
  exact format.
- Checkout can be blocked by patron standing (fines, borrowing limit). If
  a checkout fails, consult the `circulation-policies` skill rather than
  retrying blindly.
- Genre strings must match the catalog vocabulary — "sci-fi" finds nothing,
  "Science Fiction" works. See `references/GENRE_GUIDE.md`.
