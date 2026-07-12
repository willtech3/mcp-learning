# Fine Schedule and Thresholds

## How fines accrue

Fines are assessed **when a book is returned**, not continuously:

```
fine_assessed = max(0, days_overdue) * $0.25
```

`days_overdue` counts whole days past the loan's due date (default due
date = checkout date + 14 days). The `return_book` result reports both the
`fine_assessed` for that return and the patron's total `fine_outstanding`
afterwards.

Worked examples:

| Returned            | Fine    |
| ------------------- | ------- |
| on or before due    | $0.00   |
| 3 days late         | $0.75   |
| 10 days late        | $2.50   |
| 40 days late        | $10.00 → patron is now blocked |

## The two thresholds that change behavior

1. **Over $0, up to and including $10.00** — the patron may still borrow,
   but `checkout_book` interrupts with a confirmation request to the user:
   "Patron has $X.XX in outstanding fines. Proceed?" The human decides.
   If the client cannot present that confirmation, the checkout fails
   safe (no loan is created).

2. **$10.00 or more** — borrowing is blocked outright. `checkout_book`
   fails with an error; there is no confirmation escape hatch. The patron
   must pay fines down below $10.00 at the front desk before borrowing
   again. (Fine payment is a desk operation — there is no MCP tool for it,
   so do not promise to take payments.)

## Checking a patron's fines

`library://patrons/{patron_id}/history` includes the patron's current
outstanding fine balance alongside their loan records. Check it *before*
attempting a checkout for a patron who mentioned fines — you can then warn
them or route around the failure instead of discovering it mid-call.

## Books returned as `damaged` or `lost`

Condition is recorded on the return and the copy's availability is
adjusted, but replacement charges are a desk workflow, not an automatic
fine. Note the condition faithfully and direct the patron to staff for
billing questions.
