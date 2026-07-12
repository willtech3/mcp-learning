---
name: catalog-research
description: Answer analytical and research questions about the Virtual Library's collection and circulation using search_catalog, the stats resources, and the maintenance tools. Use for questions like "what do we have on X", "what's circulating most", "how is the collection distributed across genres", or when auditing and refreshing catalog data. Covers pagination discipline, choosing search versus browse resources, and interpreting the statistics endpoints.
metadata:
  author: virtual-library
  version: "1.0"
---

# Catalog Research

The catalog is a database, and this server gives you three lenses on it:
targeted search (a tool), whole-shelf browsing (resource templates), and
aggregate statistics (stats resources). Choosing the right lens is most of
the job; `scripts/search_tips.md` has worked examples.

## Lens 1 — targeted search: `search_catalog`

Best for "find books matching criteria" questions. Key arguments:

- `query`: full-text across title, description, and ISBN (max 200 chars).
- `genre` / `author`: filters; genre is exact (case-insensitive), author
  is partial match.
- `available_only`: restrict to books currently on the shelf.
- `sort_by`: `relevance` (default), `title`, `author`,
  `publication_year`, `availability`; pair with `sort_desc`.
- `page` (1-indexed) and `page_size` (max 50).

Pagination discipline: results report a total count. To enumerate a large
result set, loop `page` upward at `page_size: 50` until you have seen the
reported total — never assume one page is everything. For counting
questions, you usually only need page 1: read the total, skip the loop.

## Lens 2 — browse resources

When the question is "show me the shelf", read resources instead of
searching:

- `library://books/list` — the whole catalog (summary form).
- `library://books/{isbn}` — one authoritative record: full metadata plus
  `available_copies` / total copies.
- `library://books/by-author/{author_id}` — an author's works
  (author ids come from book records).
- `library://books/by-genre/{genre}` — one genre's shelf.

Resources are read-only and cheap; prefer them over repeated searches when
you already know the exact axis (author, genre, ISBN).

## Lens 3 — statistics

- `library://stats/circulation` — library-wide totals: active loans,
  overdue counts, aggregate circulation activity. Start here for any
  "how busy is the library" question.
- `library://stats/popular/{days}/{limit}` — most-borrowed titles over a
  trailing window, e.g. `.../popular/90/25` for the quarter's top 25.
- `library://stats/genres/{days}` — circulation share by genre over a
  window; the definitive answer to "what do our patrons actually read".

Cite the window you used ("top 10 over the last 30 days") — the same
question with a different `{days}` can rank differently.

## Deep dives on a single title

`generate_book_insights(isbn, insight_type)` produces AI-assisted analysis
grounded in the catalog record: `summary`, `themes`,
`discussion_questions`, or `similar_books`. Use it to add substance to a
research answer, after verifying the record via `library://books/{isbn}`.

## Maintenance operations (admin)

Two tools change the catalog rather than reading it — use them only when
the task is explicitly data maintenance:

- `bulk_import_books(file_path, batch_size?)` — import CSV/JSON files that
  live under the server's `data/` directory (e.g.
  `samples/books_sample.csv`). CSV headers: `isbn`, `title`,
  `author_name`, `genre`, `publication_year`, `available_copies`. The tool
  streams progress notifications batch by batch.
- `regenerate_catalog()` — long-running four-stage rebuild (integrity
  check, search indexes, circulation stats, recommendations cache). While
  it runs, the recommendations resource is temporarily unavailable and the
  server announces the visibility change. Run it after large imports so
  the stats and recommendation lenses reflect the new data.

## Answer quality checklist

- Name the lens and parameters you used (query, window, filters) so the
  answer is reproducible.
- Distinguish holdings ("we own 12 Science Fiction titles") from
  circulation ("Science Fiction was 30% of checkouts this quarter").
- If totals matter, verify you paginated to completion.
