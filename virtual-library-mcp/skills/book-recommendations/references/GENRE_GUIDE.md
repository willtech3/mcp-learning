# Genre Guide for the Virtual Library Catalog

The catalog stores one genre string per book. `search_catalog`'s `genre`
argument and the `library://books/by-genre/{genre}` resource template match
that string **case-insensitively but otherwise exactly** — colloquial
abbreviations return zero results.

## Canonical genre names

Use these exact spellings (case does not matter):

| Say this            | Not this                     |
| ------------------- | ---------------------------- |
| Science Fiction     | sci-fi, SF, scifi            |
| Fantasy             | high fantasy, epic fantasy   |
| Mystery             | whodunit, detective          |
| Thriller            | suspense                     |
| Romance             | rom-com                      |
| Historical Fiction  | hist-fic                     |
| Biography           | bio, memoirs                 |
| Non-Fiction         | nonfiction (check both!)     |
| Self-Help           | self improvement             |
| Technology          | tech, computing              |

The authoritative, current list is data-driven: read
`library://stats/genres/{days}` (e.g. `library://stats/genres/365`) and use
the genre keys it returns. When a patron's phrasing does not match, run one
`search_catalog` call with the term as `query` instead of `genre` — the
full-text index often rescues an inexact genre word.

## Mood-to-genre crosswalk

Patrons describe moods more often than genres. Reasonable starting points:

- "something gripping / can't put down" → Thriller, Mystery
- "comforting / cozy" → Romance, Fantasy
- "want to learn something" → Non-Fiction, Biography, Technology
- "escapist / take me elsewhere" → Fantasy, Science Fiction
- "true stories" → Biography, Historical Fiction, Non-Fiction

Offer picks from two adjacent genres rather than one, and say why each
matches the stated mood.

## Availability nuance

A genre browse (`library://books/by-genre/{genre}`) returns books
regardless of availability. When the patron wants to walk out with a book
today, prefer `search_catalog` with `available_only: true` — it filters to
`available_copies > 0` server-side.
