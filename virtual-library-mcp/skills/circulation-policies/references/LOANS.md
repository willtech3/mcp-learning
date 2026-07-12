# Loans, Holds, and Returns

## Loan terms

- Default loan: **14 days** from checkout. `checkout_book` computes this
  when `due_date` is omitted — prefer omitting it.
- Custom `due_date`: allowed for special cases (book club schedules,
  extended loans approved by staff). Must not be in the past.
- Each successful checkout returns a `checkout_id` (format
  `checkout_<alphanumeric>`). Preserve it — `return_book` requires it, and
  losing it means digging through
  `library://patrons/{patron_id}/history` to find the open loan.

## Renewals

There is no dedicated "renew loan" tool. The renewal pattern is:
`return_book(checkout_id)` followed by
`checkout_book(patron_id, book_isbn)` — which only succeeds if no other
patron holds a reservation claim on the copy and the patron is still
eligible. Warn the patron a renewal is not guaranteed before doing this.

## Borrowing limits

Each patron has a `borrowing_limit` (commonly 5 concurrent loans). The
count of open loans is visible in `library://patrons/{patron_id}/history`.
At the limit, `checkout_book` fails until something is returned.

## Holds (reservations)

`reserve_book` places the patron in a FIFO queue for a title with zero
available copies:

- Default expiration: 30 days from today.
- Maximum expiration: 90 days from today (later dates are rejected).
- The result includes the patron's queue `position` and an estimated wait
  (based on the title's loan turnover).
- Holds lapse silently at expiration; a patron who still wants the book
  must reserve again.

Do not place a hold on a book that has copies available — check
`library://books/{isbn}` (`available_copies`) first and just check it out.

## Returns

`return_book` restores availability immediately, assesses any late fine
(see `FINES.md`), and records condition. Encourage the optional `rating`
(1–5) and `review`: they improve the personalized recommendations served
at `library://recommendations/{patron_id}`.
