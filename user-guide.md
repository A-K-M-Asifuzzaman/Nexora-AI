# Nexora AI User Guide

> A practical guide for owners, managers, sales teams, cashiers, inventory staff,
> accountants, and system administrators.
>
> বাংলা সহায়তা: এই নির্দেশিকায় গুরুত্বপূর্ণ কাজগুলোর বাংলা ব্যাখ্যা দেওয়া
> হয়েছে, যাতে কম ইংরেজি জানা ব্যবহারকারীও সহজে সিস্টেমটি বুঝতে পারেন।

## 1. What Nexora AI does

Nexora AI connects the daily work of a business in one tenant-isolated system:

- catalog, products, units, warehouses, and stock;
- point-of-sale sessions, checkout, held carts, refunds, and reconciliation;
- customers, suppliers, quotations, sales orders, invoices, and payments;
- purchase orders, goods receipts, supplier bills, and supplier payments;
- CRM leads, opportunities, activities, and notes;
- double-entry accounting, periods, journals, and financial statements;
- VAT rates, VAT transactions, return preparation, and filing state;
- reports, forecasts, anomaly alerts, secure documents, and an AI copilot;
- organizations, branches, members, roles, permissions, audit trails, and MFA.

বাংলায়: বিক্রয়, ক্রয়, মজুত, হিসাব, ভ্যাট, ক্রেতা-সরবরাহকারী, ডকুমেন্ট ও
ব্যবসায়িক রিপোর্ট—সবকিছু একই নিরাপদ সিস্টেমে সংযুক্ত থাকে।

## 2. Client demo access

The preview login page can show a public demo account when the deployment has
`DEMO_ACCOUNT_EMAIL` and `DEMO_ACCOUNT_PASSWORD` configured.

- Select **Open demo workspace — এক ক্লিকে প্রবেশ করুন** for one-click login.
- Or copy the displayed email and password into the normal sign-in form.
- The shared demo contains synthetic business data only. Never enter real
  customer, employee, supplier, tax, payment, or confidential document data.
- Demo data may be reset. Do not depend on it as permanent storage.

বাংলায়: **Open demo workspace** বাটনে ক্লিক করলে কোনো ইমেইল-পাসওয়ার্ড টাইপ
না করেই ডেমো অ্যাকাউন্টে প্রবেশ করা যাবে। ডেমোতে বাস্তব বা গোপন তথ্য দেবেন না।

## 3. Navigation

Every major workspace is a separate URL. Changing routes loads only the selected
area, which keeps the interface fast and avoids one very long page.

| Workspace | বাংলা | URL | Purpose |
|---|---|---|---|
| Overview | সারসংক্ষেপ | `/workspace/overview` | KPIs, sales trend, product ranking, pipeline, and stock attention |
| Catalog & inventory | পণ্য ও মজুত | `/workspace/inventory` | Products, units, balances, movements, and POS |
| Sales & finance | বিক্রয় ও অর্থ | `/workspace/sales` | Parties, orders, invoices, receivables, and payables |
| Documents | নথিপত্র | `/workspace/documents` | Upload, scan, index, reindex, access-control, and delete documents |
| Forecast & alerts | পূর্বাভাস ও সতর্কতা | `/workspace/insights` | Product forecasts, model scores, and anomaly triage |
| AI copilot | এআই সহকারী | `/workspace/copilot` | Permission-aware questions using approved read-only tools |
| Organization | প্রতিষ্ঠান | `/workspace/administration` | Branches, roles, and invitations |
| User guide | ব্যবহার নির্দেশিকা | `/workspace/guide` | Visual business-process walkthroughs |

Desktop uses a full-height left sidebar. Mobile uses the menu button in the page
header. The mobile drawer can be closed with its close button, the backdrop, or
the `Escape` key.

## 4. Interface conventions

### 4.1 Clickable controls

Links, buttons, tabs, dropdowns, upload targets, and pagination controls show a
pointer and visible hover/focus state. A faded control with a blocked cursor is
disabled, usually because a required choice or permission is missing.

### 4.2 Pagination

Large lists show a limited number of records per page. Use **Previous** and
**Next**. The center label shows the current page, total pages, and record count.

বাংলায়: বড় তালিকার নিচে **Previous/Next** ব্যবহার করুন। মাঝখানে বর্তমান পৃষ্ঠা
ও মোট রেকর্ড দেখা যায়।

### 4.3 Money and quantity

- Money is exact decimal data and is transported by the API as strings.
- Do not type thousands separators into numeric inputs unless the field says it
  accepts them.
- Product quantity precision is controlled by the unit.
- The tenant's configured base currency is used throughout v1.

### 4.4 Statuses instead of deletion

Operational and financial records are not always deletable. Confirmed orders,
issued invoices, posted journals, VAT transactions, completed POS sales, and
similar evidence use status transitions, cancellation, credit notes, refunds,
or reversals. This preserves auditability.

বাংলায়: ইস্যু করা চালান বা পোস্ট করা জার্নাল সরাসরি মুছে ফেলা যায় না। ভুল
সংশোধনের জন্য cancel, refund, credit note অথবা reversal ব্যবহার করতে হবে।

## 5. Overview — সারসংক্ষেপ

Use Overview for the daily management conversation.

1. Choose **30 days**, **90 days**, or **Year to date**.
2. Read the three decision summaries first:
   - **Sales efficiency / বিক্রয় দক্ষতা** shows approximate gross margin.
   - **Cash position / নগদ অবস্থান** compares customer receivables and supplier
     payables.
   - **Action needed / করণীয়** identifies stock at reorder level.
3. Review the KPI row:
   - POS revenue;
   - gross profit after product cost;
   - customer receivables;
   - supplier payables;
   - inventory value.
4. Use **Weekly sales momentum** to see direction, not merely a total.
5. Open **View weekly values** for an accessible table of chart data.
6. Review **Top products**, **Opportunity pipeline**, and **Stock watch**.
7. Select the refresh icon when you need the latest committed records.

The dashboard never fabricates missing values. A warning explains when a report
is unavailable or the user's role cannot read it.

## 6. Catalog and inventory — পণ্য ও মজুত

### 6.1 Create a unit

1. Open **Catalog & inventory**.
2. Enter a short unit code such as `EA` and a name such as `Each`.
3. Set precision (`0` for whole pieces; a higher value for divisible units).
4. Select **Add unit**.

### 6.2 Create a product

1. Enter a unique SKU.
2. Enter the product name.
3. Choose its unit.
4. Enter the selling price.
5. Select **Add product**.

Use pagination to confirm the product appears. Product names used by stock rows
are resolved across the complete product catalog, not only the first API page.

### 6.3 Receive or issue stock

1. Choose **Receive stock** or **Issue stock**.
2. Select the warehouse and product.
3. Enter quantity.
4. For a receipt, enter unit cost when required.
5. Select **Post movement**.
6. Confirm the balance and recent movement list change.

Stock must change through the movement ledger. Direct balance editing is not a
supported workflow.

বাংলায়: মজুত বাড়াতে **Receive stock**, কমাতে **Issue stock** নির্বাচন করুন।
সরাসরি balance পরিবর্তন করা যায় না; প্রতিটি পরিবর্তনের movement record থাকে।

### 6.4 Point of sale

1. Choose a POS terminal.
2. Select **Open shift** and enter the opening float when requested.
3. Add products to the cart.
4. Review quantities, discounts, tax, total, and tender.
5. Complete checkout with the exact tender information.
6. Print or retain the generated receipt reference.
7. Use hold/resume when a customer pauses a transaction.
8. Use refund only with the required permission and an auditable reason.
9. Close the session with counted cash; review the calculated variance.

Checkout is atomic: sale, tender, stock movement, cost, VAT, journal, receipt,
and audit evidence commit together or none commit.

## 7. Sales and finance — বিক্রয় ও অর্থ

### 7.1 Customers and suppliers

- Create customers and suppliers with unique codes and clear legal/display
  names.
- Use the combined paginated relationship list to distinguish each party type.
- A party referenced by business documents should be deactivated or updated,
  not casually removed.

### 7.2 Sales order lifecycle

1. Create or select a customer.
2. Select a product, quantity, and exact unit price.
3. Create the draft order.
4. Confirm the order when customer acceptance is established.
5. Fulfil from the correct warehouse.
6. Create the invoice from the business event.
7. Issue the invoice; its official number is assigned at issue time.
8. Record payment against the invoice.
9. Review receivables until outstanding reaches zero.

Do not delete a completed commercial chain. Cancel a permitted draft/confirmed
record, or use a credit note/refund after posting.

বাংলায়: অর্ডার → confirm → fulfil → invoice → issue → payment ক্রম অনুসরণ
করুন। ইস্যু করা invoice মুছে না দিয়ে credit note ব্যবহার করুন।

### 7.3 Receivables and payables

- **Owed to you** is outstanding customer money.
- **You owe** is outstanding supplier money.
- The party row separates invoiced/paid totals from the outstanding amount.

## 8. Purchasing — ক্রয়

The purchasing domain supports:

1. supplier selection and purchase-order creation;
2. confirmation or cancellation;
3. goods receipt into the inventory ledger;
4. supplier-bill creation and issue;
5. supplier payment;
6. payables and AP-aging reports.

Receipt changes stock; bill issue creates the liability and accounting/VAT
evidence. These are separate events because goods and invoices can arrive at
different times. Advanced purchasing operations are available through the
authenticated API and service workflows even when a role's client navigation
does not expose a dedicated editing screen.

## 9. CRM — ক্রেতা সম্পর্ক ব্যবস্থাপনা

The CRM flow is:

`Lead → Qualified lead → Customer + Opportunity → Activities/Notes → Won/Lost`

- Create leads with source and contact information.
- Change lead status as qualification progresses.
- Convert a qualified lead once; conversion is idempotent.
- Move opportunities only through valid stages.
- Complete follow-up activities rather than deleting evidence.
- Attach notes to the supported CRM entity.

The Overview pipeline chart uses the same opportunity data.

## 10. Documents and RAG — নথিপত্র

### 10.1 Upload

1. Open **Documents**.
2. Choose PDF, text, Markdown, or CSV.
3. Add a meaningful title.
4. Optionally restrict visibility to selected roles.
5. Select **Upload**.

The upload is scanned, stored, and indexed asynchronously. Status moves through
the indexing lifecycle. Do not expect a document to answer questions until it
is indexed.

### 10.2 Reindex and delete

- **Reindex** queues safe reprocessing.
- **Delete** removes the database record immediately and queues storage/vector
  cleanup through the outbox and background worker.
- Deletion can take time to disappear from external storage because cleanup is
  asynchronous and retried.

বাংলায়: upload করার পর indexing শেষ হওয়া পর্যন্ত অপেক্ষা করুন। ভুল হলে
**Reindex** দিন। **Delete** দিলে background worker নিরাপদে file ও vector মুছবে।

## 11. Forecast and anomaly alerts — পূর্বাভাস ও সতর্কতা

### 11.1 Forecast

1. Choose a product with sufficient sales history.
2. Select the number of future periods.
3. Review forecast values and uncertainty bounds.
4. Review model scores. The winning model is selected from measured backtests.

Forecasts are decision support, not guaranteed demand. A model with insufficient
history must say so rather than invent a prediction.

### 11.2 Alerts

- Filter open, acknowledged, dismissed, or all alerts.
- Select **Run detectors now** to queue detection.
- **Acknowledge** means someone has seen and owns the investigation.
- **Dismiss** means the event was reviewed and is not actionable.
- Sensitive details may be redacted according to role.

## 12. AI copilot — এআই সহকারী

Ask focused questions such as:

- "Which products generated the most revenue this month?"
- "Show the current receivables risk."
- "Which stock items need attention?"
- "Summarize the indexed operations playbook."

The copilot is read-only. It selects from permission-checked tools, never writes
business data, and never generates SQL. Numerical grounding checks require
figures in an answer to exist in authorized tool output.

বাংলায় প্রশ্নের উদাহরণ: “এই মাসে কোন পণ্য সবচেয়ে বেশি বিক্রি হয়েছে?” অথবা
“কোন পণ্যের মজুত কম?” উত্তর যাচাই করে তারপর ব্যবসায়িক সিদ্ধান্ত নিন।

## 13. Accounting — হিসাবরক্ষণ

- Accounts define the chart of accounts.
- Periods control when posting is permitted.
- Every journal entry must balance debit and credit.
- A posted journal is immutable.
- Corrections use a linked reversal, never an edit.
- Trial balance, profit and loss, balance sheet, and general ledger are derived
  from posted entries.

Business workflows post accounting automatically where specified. Manual
journals require the accounting permission and the same balance/period rules.

## 14. VAT — ভ্যাট

- VAT rates are effective-dated configuration.
- Price calculation identifies net, VAT, and gross values.
- Sales and purchasing events create VAT transactions.
- A VAT return summarizes the selected period.
- Filing changes the return to an immutable filed state.

Nexora provides a generic configurable VAT subsystem. It does not claim NBR or
Bangladesh Mushak certification unless a separately verified jurisdiction pack
is installed and approved.

## 15. Organization and access — প্রতিষ্ঠান ও অনুমতি

### 15.1 Branches

- Create a branch with a unique uppercase code and clear name.
- The default branch is identified in the list.
- Deactivation/deletion is blocked when it would violate business invariants,
  such as removing the last active branch.

### 15.2 Invitations and roles

1. Enter the colleague's email.
2. Choose a server-provided role.
3. Select **Send invite**.
4. The recipient completes the secure invitation flow.

Only grant permissions the current actor is allowed to grant. A user cannot
escalate their own role, and the last owner cannot be removed.

### 15.3 Tenant switching

Use the organization selector. The server validates active membership and
issues a new tenant-scoped session. A client-supplied tenant identifier is never
trusted as authorization.

## 16. Security and audit behavior

- Authentication uses secure token/session handling through the frontend BFF.
- Sensitive state-changing requests require CSRF protection.
- Tenant access is enforced in authenticated context, ORM filtering, and
  PostgreSQL RLS.
- Cross-tenant object access returns not found rather than revealing existence.
- MFA/TOTP is available for account hardening.
- Business audit events commit with their business transaction.
- Security events survive failed/rolled-back requests.
- Audit chains use a concurrency-safe sequence and tamper-evident hashes.
- Upload antivirus scanning, rate limits, CSP, secure headers, and encrypted
  TOTP secrets are part of the production design.

## 17. Troubleshooting

### A page redirects to login

The session is absent or expired. Sign in again or use the public demo button on
the preview deployment.

### A section says it is unavailable

The signed-in role may lack its read permission, or a dependency may be
temporarily unavailable. Do not repeatedly submit a write action. Refresh once,
then ask an administrator to verify permissions and service health.

### A button is disabled

Check required fields and selections. Some actions require a valid lifecycle
state—for example, only a draft invoice can be issued.

### Stock or product name looks wrong

Refresh the inventory route. Catalog lookup loads all catalog pages so existing
stock should not display an unknown product.

### Forecast says there is insufficient history

Choose a product with more completed sales or wait until enough real history is
collected. Do not treat a fabricated fallback as a forecast.

### Upload is still processing

Indexing is asynchronous. Confirm worker, outbox, object storage, antivirus, and
Qdrant health before reindexing repeatedly.

### Browser reports an SSL protocol error on localhost

Use `http://localhost:<port>`, not HTTPS. Local production-mode preview does not
emit `upgrade-insecure-requests`; HTTPS deployments behind the reverse proxy do.

## 18. Demo operator checklist

Before showing a client:

1. Open the public URL in a clean browser session.
2. Confirm the demo credential card and one-click login.
3. Confirm redirect to `/workspace/overview`.
4. Visit every route directly and from navigation.
5. Verify dashboard values, chart, table fallback, pipeline, and stock watch.
6. Verify pagination changes records.
7. Verify add/create and allowed status-transition actions.
8. Verify document upload/reindex/delete with a disposable synthetic file.
9. Verify a forecast with real seeded history.
10. Verify alert filtering and state changes.
11. Ask one authorized Copilot question and inspect degraded/error behavior if
    no paid model provider is configured.
12. Check browser console and failed network requests.
13. Check desktop and mobile widths, burger drawer, focus states, and keyboard.
14. Run accessibility checks.
15. Confirm API readiness, worker, beat, PostgreSQL, Redis, MinIO, Qdrant, and
    ClamAV health.

## 19. Deployment separation

### Client preview

The free preview may consolidate services onto one host to reduce cost. It still
keeps PostgreSQL, Redis, API, frontend, Celery worker, Celery beat, outbox,
MinIO, Qdrant, ClamAV, mail sink, and reverse proxy as real services.

### Production

Production architecture remains separate and scalable. Do not remove Celery,
outbox, Qdrant, ClamAV, object storage, RLS, audit chaining, or transactional
boundaries merely to fit a free demo host.

Production readiness additionally requires real secrets, TLS/domain, SMTP,
backups and restore drills, monitoring/alerts, capacity planning, WAF strategy,
provider keys where enabled, and an external security assessment.

## 20. Product boundaries

- Nexora is not a payment processor and must not store PAN, CVV, or track data.
- v1 uses one base currency per tenant.
- one tenant represents one legal entity; branches are operational units.
- the AI is read-only.
- forecasts are probabilistic decision support.
- jurisdiction-specific tax certification is not implied.

These boundaries protect the client from assuming a capability or certification
that has not been independently verified.
