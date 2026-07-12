# Worked Search Recipes

Concrete `search_catalog` argument sets for common research questions.
Copy the shape, adjust the values.

## "What do we have about dragons that I can borrow today?"

```json
{ "query": "dragons", "available_only": true, "page_size": 20 }
```

Full-text `query` beats a genre filter for topical questions — a dragon
book can be Fantasy, Science Fiction, or a children's Non-Fiction title.

## "List every Mystery title we own, newest first"

```json
{ "genre": "Mystery", "sort_by": "publication_year", "sort_desc": true,
  "page": 1, "page_size": 50 }
```

Then increment `page` until you have collected the reported total. At
`page_size: 50` (the maximum), a 240-title genre takes 5 calls.

## "Do we have anything by Le Guin?"

```json
{ "author": "le guin", "page_size": 50 }
```

`author` is a partial, case-insensitive match — surname alone is the
robust choice. To then list her complete works, take `author_id` from any
result and read `library://books/by-author/{author_id}`.

## "Is this exact book in the catalog?"

```json
{ "query": "9780261102217" }
```

ISBNs are indexed by the full-text search. For the authoritative record
(copies owned, copies available), read `library://books/{isbn}` directly.

## "What's checked out the most right now?"

Not a search — use the stats lens:

- `library://stats/popular/30/10` — top 10 by checkouts, last 30 days.
- `library://stats/circulation` — library-wide loan/overdue totals.

## Anti-patterns

- **Zero results for a genre** — you probably used a colloquial name
  ("sci-fi"). Retry the term as `query`, or read
  `library://stats/genres/365` to see the canonical genre vocabulary.
- **`page_size` over 50** — rejected by the schema; 50 is the ceiling.
- **Screen-scraping availability from search snippets** when you need
  exact copy counts — read `library://books/{isbn}` instead.
