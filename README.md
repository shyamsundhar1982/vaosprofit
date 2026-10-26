# RetailPilot · Supermarket Replenishment MVP

An integration-first, multi-retailer supermarket forecasting and replenishment pilot. Built for validating demand planning with 2–3 consenting supermarkets. This is **not a production SaaS deployment or an automatic purchasing system**.

## Cloud demo (no local PC needed)

Open **https://vaosprofit-retailpilot.vayushastr.workers.dev/** and select **Explore synthetic demo**. The demo is read-only and uses fabricated sample goods and sales. It is hosted by Cloudflare Workers; the separate D1 database is provisioned for future authorized retailer accounts. Nothing in the public demo accesses genuine supermarket data.

Cloud implementation and operations: [`cloud/README.md`](cloud/README.md). Code is stored in **`shyamsundhar1982/vaosprofit`**.

The Python implementation described below remains as a validated developer/reference build, but is not required for viewing or using the cloud demo.

## What is implemented

- Tenant-scoped product, store, inventory and daily sales storage in SQLite.
- API tokens scoped to a tenant; stores are separate within each tenant.
- UTF-8 CSV imports for products, inventory and sales; all-or-nothing batch validation, upserts for re-imports.
- Deterministic 7-day trend blended with 14/28-day baseline; expected target stock, lead time, safety stock, review cycle, case-pack and minimum order constraints.
- Data completeness and inventory freshness gates, perishable and potential stockout review flags.
- Draft-only purchase suggestions with estimated value, review dashboard and CSV export.
- 7-day walk-forward forecast diagnostic versus a simple naive baseline.
- Automated calculations, invalid import, isolation and local API contract tests.

## Requirements

- Python 3.11+ (no package installation needed).
- A Windows, macOS or Linux computer with local file storage.
- Modern browser; all data stays on the machine running this local demonstration.

## Optional local reference run (for developers)

Open PowerShell or Terminal in the directory containing `retailpilot/`:

```powershell
python -m retailpilot --db retailpilot.sqlite3 seed-demo
python -m retailpilot --db retailpilot.sqlite3 serve
```

`seed-demo` creates **synthetic** sales and two isolated pilot retailers. Copy one of the generated API tokens immediately; it is not stored in cleartext. Open **http://127.0.0.1:8766** and paste the token. The demo assumes you have not previously created the demo tenants in this database; use a fresh DB filename for a clean second demo.

Do not reuse demonstration accounts or tokens for real customer data.

To create a retailer without demo data:

```powershell
python -m retailpilot --db live-pilot.sqlite3 init
python -m retailpilot --db live-pilot.sqlite3 create-tenant --tenant store-a --name "Pilot Store A" --store main --store-name "Main Branch"
python -m retailpilot --db live-pilot.sqlite3 serve
```

To add another store to that retailer:

```powershell
python -m retailpilot --db live-pilot.sqlite3 add-store --tenant store-a --store north --name "North Branch"
```

Each additional supermarket company should receive its **own** tenant ID and secret token. Keep tokens out of chat, screenshots and shared reports. Use a separately controlled device/database for real customer information until the security checklist is complete.

## Required CSV schemas

Template headers are provided in `templates/`. Save as UTF-8 CSV and import from the dashboard in the following order:

1. `products.csv`: `sku,name,supplier,unit_cost,unit_price,lead_days,safety_days,pack_size,min_order_qty,shelf_life_days`
2. `inventory.csv`: `store_id,sku,on_hand,on_order,snapshot_date`
3. `sales.csv`: `store_id,sku,date,units`

Rules:

- `date` and `snapshot_date` are ISO `YYYY-MM-DD` in the store's local business calendar.
- Money columns are in the same currency for each tenant (the dashboard currently displays ₹). They are for **estimation**, not authoritative financial posting.
- Quantities and lead times are nonnegative integers; prices are nonnegative decimals; pack size is at least 1.
- `shelf_life_days=0` means the shelf-life review flag is disabled for that item (not that the item never expires).
- **Sales require one row per SKU per completed business day, including explicit `units=0`.** Missing rows are treated as missing data, not zero demand. Import at least 28 days; ideally 90–365 days for the real pilot.
- Inventory and `on_order` should reflect the selected `as_of` date, not estimated stock from the sales file.
- For a working recommendation, each product needs 14 consecutive completed days of sales and a stock snapshot no more than 1 day away from `as_of`.
- Upload **up to 30,000 rows per batch** (10 MiB max); split large sales exports into chronological chunks. Re-imports replace the matching daily aggregate, they do not add to it.
- The first version expects already-cleaned daily net units. Data correction and mapping from vendor POS transaction formats is done during each connector onboarding.

## API for integration developers

Use `Authorization: Bearer <retailer token>` on every endpoint except health and dashboard. This browser app uses the same API, with no CORS and no cookies.

| Method | Route | Description |
| --- | --- | --- |
| GET | `/api/health` | Process status (public) |
| GET | `/api/me` | Tenant identity and stores |
| POST | `/api/import/products` | Send plain UTF-8 CSV (`text/csv`) |
| POST | `/api/import/inventory` | Send plain UTF-8 CSV |
| POST | `/api/import/sales` | Send plain UTF-8 CSV |
| GET | `/api/recommendations?store=main&as_of=YYYY-MM-DD&review_days=7` | SKU recommendations |
| GET | `/api/summary?store=main&as_of=YYYY-MM-DD` | Operational summary |
| GET | `/api/backtest?store=main&as_of=YYYY-MM-DD` | 7-day holdout forecast diagnostic |
| GET | `/api/drafts.csv?store=main&as_of=YYYY-MM-DD` | **Draft only**, never sent to supplier |

Errors return JSON with HTTP 400, 401, 404, 413 or 415. Missing or invalid authorization returns 401. Store access is derived from the token's tenant; no import payload can select an alternate tenant.

## Forecast/reorder logic (transparent pilot baseline)

On a completed as-of business date:

1. Estimate daily demand as `0.6 × last-7-day average + 0.4 × last-28-day average` (last 14 days if the earlier period is incomplete).
2. Calculate `target = ceil(daily demand × (supplier lead days + safety days + review cycle days))`.
3. Subtract stock on hand and already ordered stock; round the positive deficit to a supplier pack multiple and respect minimum order quantity.
4. Withhold when the sales data or stock snapshot is insufficient. Flag short shelf-life products and zero stock for manual review.
5. Export as a **purchase proposal**, not an actual placed purchase order.

This is an interpretable baseline. It does not yet model promotions, past out-of-stocks, holidays, substitutions, lot-level expiration, supplier fill rates, transfer inventory, censored demand or service-level uncertainty. A pilot must compare it against the store's current method before moving to a production ML model.

## Test

```powershell
python -m unittest discover -s tests -v
python -m compileall -q retailpilot
```

The local API integration test briefly opens an ephemeral `127.0.0.1` port; network-restricted sandboxes may need permission for this test.

## Security and release boundary

- Runs **only on loopback** and does not expose an internet-facing server.
- SQLite uses tenant-scoped composite keys; every API read/write uses authorization-derived tenant context.
- Tokens are randomly generated, SHA-256 hashed at rest and shown only once on creation.
- No payment credentials, customer PII, staff profiles, raw CCTV footage, live supplier submission or unattended purchases.
- No third-party model/API, cloud subscription or mandatory paid software.
- Real multi-customer SaaS needs an independent security review, TLS, rotating scoped credentials, role-based access, Postgres with row-level protections, backups/restore drills, encryption/key management, audit retention, observability, privacy documentation and disaster recovery before exposure to the internet.
- Product pricing, unit economics, returns, taxes, forecasting and purchase limits must be signed off by each pilot retailer. This MVP is not GST accounting software.

See `PILOT_REQUIREMENTS.md` for onboarding, legal/data checks, metrics, acceptance criteria and next-release gates.
