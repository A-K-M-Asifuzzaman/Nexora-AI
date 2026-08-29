# Nexora AI — Accounting Design

> Phase 0 baseline: invariants, account model, posting rules and assumptions.
> Detailed implementation design lands in Phase 5. Nothing in Phases 1–4 may
> contradict the invariants in §1.

---

## 1. Invariants (never negotiable)

1. **Every posted journal entry balances:** `SUM(debit) = SUM(credit)`.
2. **A posted entry is immutable.** No UPDATE, no DELETE. Corrections are made
   by posting a **reversal** entry.
3. **Every line is either a debit or a credit, never both, never zero.**
4. **No posting into a CLOSED or LOCKED fiscal period.**
5. **All amounts are `Decimal` / `NUMERIC`.** No float touches a monetary value
   at any point in its lifecycle.
6. **Every entry is tenant-scoped** and references a source document.
7. **Inventory movements and their accounting postings commit in the same
   transaction.** Stock and books never diverge.

Invariants 1–4 are enforced **in the database** (`DATABASE.md` §7), not only in
services. Application validation is a UX affordance; the constraint is the
guarantee. A bug in a service, a data-fix script or a future module must not be
able to create an unbalanced ledger.

---

## 2. Account Model

```
ASSET       normal balance DR    increases DR, decreases CR
LIABILITY   normal balance CR    increases CR, decreases DR
EQUITY      normal balance CR
REVENUE     normal balance CR
EXPENSE     normal balance DR
```

`accounts`: `id, tenant_id, code, name, type, parent_id, is_postable,
is_system, currency, is_active`.

- Accounts form a tree; **only leaf accounts are postable** (`is_postable`).
  Posting to a parent breaks subtotal arithmetic in every report.
- `is_system` accounts (AR control, AP control, VAT payable, VAT receivable,
  Inventory, COGS, Retained Earnings, Rounding Difference) are created at tenant
  onboarding, referenced by code from posting rules, and cannot be deleted.
- `UNIQUE (tenant_id, code)`.

### 2.1 Default chart of accounts (seeded per tenant)

```
1000 ASSETS
  1100 Current Assets
    1110 Cash on Hand              system: CASH
    1120 Bank Accounts             system: BANK
    1130 Accounts Receivable       system: AR_CONTROL
    1140 Inventory                 system: INVENTORY
    1150 Input VAT Receivable      system: VAT_INPUT
1500 Fixed Assets
2000 LIABILITIES
  2100 Accounts Payable            system: AP_CONTROL
  2200 Output VAT Payable          system: VAT_OUTPUT
  2300 Accrued Liabilities
3000 EQUITY
  3100 Owner's Capital
  3200 Retained Earnings           system: RETAINED_EARNINGS
4000 REVENUE
  4100 Sales Revenue               system: SALES_REVENUE
  4200 Sales Returns & Allowances  system: SALES_RETURNS   (contra-revenue)
  4300 Sales Discounts             system: SALES_DISCOUNTS (contra-revenue)
5000 EXPENSES
  5100 Cost of Goods Sold          system: COGS
  5200 Operating Expenses
  5900 Rounding Difference         system: ROUNDING
```

The tenant may extend this tree; system accounts remain.

---

## 3. Posting Rules

Posting rules are **data-driven**, resolved by system account code, not
hardcoded account ids. Each rule is a pure function
`(business event) → list[JournalLine]`, unit-testable without a database.

### 3.1 Cash sale (VAT-exclusive pricing)

Goods 1,000.00, VAT 15% = 150.00, cost of goods 600.00.

```
Cash on Hand              DR  1,150.00
    Sales Revenue                       CR  1,000.00
    Output VAT Payable                  CR    150.00

Cost of Goods Sold        DR    600.00
    Inventory                           CR    600.00
```

Two entries, one transaction: revenue recognition and cost recognition are
separate accounting events with different reversal semantics, and keeping them
separate makes a sales-return that restocks (reverse both) distinguishable from
a price adjustment (reverse revenue only).

### 3.2 Credit sale

Identical, with `Accounts Receivable DR` replacing `Cash`.

### 3.3 Customer payment

```
Cash / Bank               DR  1,150.00
    Accounts Receivable                 CR  1,150.00
```

Allocated against specific invoices via `payment_allocations`. Unallocated
payments sit as customer credit; the sum of allocations may never exceed the
payment amount (`CHECK` + service validation).

### 3.4 Purchase — goods receipt

```
Inventory                 DR    600.00
    Goods Received Not Invoiced         CR    600.00
```

Receipt and supplier bill are separate events. Goods frequently arrive before
the invoice; recognising the liability only at receipt would misstate AP, and
posting nothing would misstate inventory. GRNI is the standard bridge.

### 3.5 Supplier bill

```
Goods Received Not Invoiced DR  600.00
Input VAT Receivable        DR   90.00
    Accounts Payable                    CR   690.00
```

### 3.6 Supplier payment

```
Accounts Payable          DR    690.00
    Bank                                CR    690.00
```

### 3.7 Sales return / refund

Reverse revenue and, if goods are restocked, reverse cost:

```
Sales Returns & Allowances  DR 1,000.00
Output VAT Payable          DR   150.00
    Cash / Accounts Receivable          CR 1,150.00

Inventory                   DR   600.00     (only if restocked)
    Cost of Goods Sold                  CR   600.00
```

A contra-revenue account is used rather than debiting Sales Revenue directly, so
gross sales and returns remain separately reportable — a return rate that is
invisible in the ledger is a return rate nobody manages.

Restock uses the **original sale's cost**, not the current average cost.
Otherwise a return during a price change silently creates or destroys margin.

### 3.8 Expense

```
Operating Expense         DR
Input VAT Receivable      DR
    Cash / Bank / Accounts Payable      CR
```

---

## 4. Inventory Valuation

**Weighted Average Cost (moving average), perpetual** (ADR-0018).

- Perpetual: COGS is recognised at each sale, so margin is available in real
  time. Periodic valuation would make the dashboard's gross-profit tile a
  month-end figure, which defeats its purpose.
- Moving average over FIFO: FIFO requires cost layers, layer consumption
  tracking, and layer-aware returns — materially more machinery. Weighted
  average is accepted under IFRS and most local GAAP, and is what SMB
  accountants expect.

Cost is maintained per `(tenant_id, product_id)`:

```
new_avg_cost = (qty_on_hand * old_avg_cost + received_qty * received_unit_cost)
               / (qty_on_hand + received_qty)
```

Edge cases (all tested):

- Receipt when `qty_on_hand` is 0 or negative → average cost is set to the
  received unit cost, not computed from a meaningless denominator.
- Transfers between warehouses move at current average cost — no gain or loss.
- Returns to a supplier reduce inventory at current average cost; the difference
  against the original purchase price posts to a purchase-price-variance
  account.
- FIFO remains implementable later: `product_cost_layers` is reserved in the
  schema so a future switch is additive rather than a rewrite.

---

## 5. Fiscal Periods

`fiscal_periods`: `tenant_id, name, start_date, end_date, status`.
Status: `OPEN` → `CLOSED` → `LOCKED`.

- `OPEN` — posting allowed.
- `CLOSED` — normal posting rejected; a user with `accounting.post_closed` may
  post an adjustment, which is audited distinctly.
- `LOCKED` — no posting under any permission. Terminal.

Periods derive from `tenants.fiscal_year_start_month`. Non-overlap is enforced
with an exclusion constraint (`btree_gist`), so overlapping periods — which
would make every period report ambiguous — cannot exist:

```sql
EXCLUDE USING gist (tenant_id WITH =, daterange(start_date, end_date, '[]') WITH &&)
```

Year-end close posts a closing entry moving net income to Retained Earnings.
It is a normal, reversible journal entry, not a special mutation.

---

## 6. Rounding

**`ROUND_HALF_UP`, applied per line, then summed** (`DATABASE.md` §2.1).

Amounts are stored at 4 decimal places and rounded to the currency's minor units
(`currencies.minor_units`) for posting and presentation.

Worked example — 3 items at 33.333 with 15% VAT, BDT (2 dp):

```
Line net    33.33 + 33.33 + 33.33  = 99.99
Line VAT     5.00 +  5.00 +  5.00  = 15.00     (33.333 × 0.15 = 4.99995 → 5.00)
Total                               = 114.99
```

Computing VAT on the rounded total instead gives `99.99 × 0.15 = 15.00` — the
same here, but the two methods diverge on other inputs. **Per-line is the
committed rule**, because each printed line must be independently verifiable by
the person holding the invoice.

Where a rounding difference of at most one minor unit arises between subsystems,
it posts to the **Rounding Difference** account rather than being silently
absorbed. A ledger that quietly swallows discrepancies cannot be audited.

---

## 7. Reversals

Correction is **only** by reversal (invariant 2).

A reversal entry: same date or a later date (never earlier — that would alter a
closed period retroactively), debits and credits swapped, `reversal_of_entry_id`
set, `reversed_by_entry_id` written back on the original. Both links are the
only columns a posted entry may ever have written, and the immutability trigger
whitelists exactly those.

An entry may be reversed once. A second attempt → `ENTRY_ALREADY_REVERSED`.
Reversing an entry in a closed period posts the reversal into the current open
period, with the original date recorded in metadata.

---

## 8. Reports

| Report | Definition |
|---|---|
| General Ledger | All lines for an account in a period, running balance |
| Trial Balance | Per-account DR/CR totals; **total DR must equal total CR** |
| Profit & Loss | Revenue − Expense for a period |
| Balance Sheet | Assets = Liabilities + Equity at a date |
| AR Aging | Outstanding receivables by bucket: current, 1–30, 31–60, 61–90, 90+ |
| AP Aging | Same for payables |

All aggregation happens **in the database**. No report loads raw rows into
Python to sum them — that is both slow and, on a large tenant, a memory
incident.

The Trial Balance is a live integrity check: if total debits ≠ total credits,
the ledger is corrupt and that is a P0. An automated test asserts this after
every integration scenario in the accounting suite.

---

## 9. Assumptions (explicit)

1. **Single currency per tenant** in v1. `currency` is stored on every
   monetary record from day one so multi-currency is an additive change, not a
   migration of every table.
2. **Accrual basis** accounting.
3. **Perpetual inventory, weighted average cost** (§4).
4. **VAT is configurable and generic** — no jurisdiction's rules are hardcoded.
   Nexora AI does **not** claim NBR or Bangladesh Mushak compliance. Regulatory
   report generation stays isolated in the `vat` module so verified
   jurisdiction-specific support can be added without touching the accounting
   core.
5. **No multi-entity consolidation** in v1. One tenant = one legal entity.
   Branches are operational, not legal, divisions.
6. **No dedicated fixed-asset depreciation module** in v1; depreciation is
   posted as a manual journal entry.

Every assumption is a candidate for a future ADR. None may be quietly violated
by an implementation.

---

## 10. Test Matrix (Phase 5, binding)

| # | Scenario | Expected |
|---|---|---|
| 1 | Balanced entry posts | success |
| 2 | Debit 100 / Credit 90 | **rejected** `UNBALANCED_JOURNAL` |
| 3 | Unbalanced insert bypassing the service | **rejected by DB trigger** |
| 4 | UPDATE a posted entry | **rejected by DB trigger** |
| 5 | DELETE a posted entry | **rejected by DB trigger** |
| 6 | Reversal restores account balances to pre-entry state | balances equal |
| 7 | Double reversal | `ENTRY_ALREADY_REVERSED` |
| 8 | Post into CLOSED period | `PERIOD_CLOSED` |
| 9 | Post into LOCKED period, elevated permission | still rejected |
| 10 | Overlapping fiscal periods | rejected by exclusion constraint |
| 11 | Cash sale posting | matches §3.1 exactly |
| 12 | Credit sale → payment → allocation | AR nets to zero |
| 13 | Goods receipt → bill → payment | GRNI and AP net to zero |
| 14 | Sales return with restock | inventory and COGS restored at original cost |
| 15 | Trial balance after a full scenario suite | total DR = total CR |
| 16 | Tenant B reads Tenant A's journal | `404` |
| 17 | User without `accounting.post` posts | `403` |
| 18 | Line with both debit and credit non-zero | rejected by `CHECK` |
| 19 | Posting to a non-postable parent account | rejected |
| 20 | Concurrent postings to the same account | both succeed, balances correct |
| 21 | Rounding difference routed to Rounding account | balanced |
| 22 | Moving average after receipt at a new price | matches §4 formula |
