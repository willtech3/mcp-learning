---
name: circulation-policies
description: Apply the Virtual Library's lending policies correctly when checking books out, processing returns, placing holds, and renewing memberships. Use whenever you operate the checkout_book, return_book, reserve_book, or renew_membership tools, or when a patron asks about due dates, fines, borrowing limits, or why a checkout was refused. Explains the fine schedule, blocking thresholds, and the confirmation step for patrons with outstanding fines.
license: MIT
---

# Circulation Policies

These are the rules the circulation tools enforce. Knowing them lets you
predict failures, explain refusals to patrons accurately, and avoid
retrying calls that will never succeed.

## Policy at a glance

| Policy                     | Value                                          |
| -------------------------- | ---------------------------------------------- |
| Standard loan period       | 14 days (default `due_date` on checkout)       |
| Late fine                  | $0.25 per day overdue, assessed at return      |
| Checkout block threshold   | outstanding fines of $10.00 or more            |
| Fine confirmation range    | fines over $0 and up to $10 → user confirms    |
| Hold (reservation) default | expires 30 days out                            |
| Hold maximum               | 90 days out                                    |
| Borrowing limit            | per patron (`borrowing_limit`, typically 5)    |

Full detail: `references/FINES.md` (fine math and thresholds) and
`references/LOANS.md` (loans, holds, and returns).

## Identifier formats

- Patron ids: `patron_` + at least 5 alphanumerics, e.g. `patron_00042`.
- Checkout ids: `checkout_` + alphanumerics — returned by `checkout_book`;
  you need it for `return_book`. Also visible in
  `library://patrons/{patron_id}/history`.
- ISBNs: 13 digits, no hyphens.

## Checking out — `checkout_book(patron_id, book_isbn, due_date?, notes?)`

Eligibility, checked server-side in this order:

1. Patron exists and status is `active` (statuses: `active`, `suspended`,
   `expired`, `pending` — see `library://patrons/by-status/{status}`).
2. Patron is under their borrowing limit.
3. Outstanding fines are under $10.00.
4. The book has at least one available copy.

If fines are over $0 but at most $10.00, the tool pauses and asks the
*user* to confirm proceeding (an elicitation). Do not answer this
confirmation yourself — it is a human judgment call. If declined, the
checkout is not performed.

`due_date` may be set for a custom loan but cannot be in the past. Omit it
for the standard 14-day loan.

## Returning — `return_book(checkout_id, condition?, notes?, rating?, review?)`

- `condition` is one of `excellent`, `good` (default), `fair`, `damaged`,
  `lost`. Record damage honestly and put specifics in `notes`.
- Late returns are fined automatically at $0.25/day past the due date; the
  result reports `fine_assessed` and the patron's `fine_outstanding`.
- Optionally record a `rating` (1–5) and `review` — these feed the
  recommendation data.

## Holds — `reserve_book(patron_id, book_isbn, expiration_date?, notes?)`

Use when a wanted book has no available copies. The result reports the
patron's queue position and estimated wait. `expiration_date` must be in
the future and at most 90 days out; omitted, it defaults to 30 days.

## Membership — `renew_membership(patron_id)`

Expired memberships block borrowing. The renewal term (duration) is *not*
a tool argument: the tool elicits it from the user mid-call. Expect that
interaction and let the user choose.

## Explaining refusals

When a circulation tool refuses, translate the policy for the patron:

- "fines exceed $10" → they must pay down fines below $10.00 first.
- "borrowing limit reached" → something must be returned first; list their
  open loans from `library://patrons/{patron_id}/history`.
- "no available copies" → offer `reserve_book` and quote the queue position
  from its result.
- patron `suspended` / `expired` / `pending` → borrowing is unavailable
  until the status is resolved; for `expired`, offer `renew_membership`.

Never bypass a policy by inventing arguments (e.g. back-dating `due_date`
is rejected). Policies live server-side; your job is to apply and explain
them.
