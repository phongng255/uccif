# Trip Budget

Shared expense tracker for a 3-day / 2-night group trip. Each entry is one of:

- `Thu` — money paid into the group fund (income)
- `Chi` — money spent from the fund (expense)
- `Chuyển` — a transfer between two members; it is neither income nor expense

Amounts are stored in VND. The exchange-rate service converts THB receipts at entry time.

Conventions: amounts are integers (no floats); every store action goes through `ledgerStore`.
