# Live-data Pilot Requirements · RetailPilot 0.1

**Prepared:** 26 October 2026 (India). **Commercial strategy:** independent, integration-first, multi-tenant SaaS for Indian supermarkets. **First wedge:** demand planning and supervised auto-replenishment. **Pilot target:** 2–3 consenting supermarkets, not an unsupported revenue/ROI claim.

## 1. Pilot decision and scope

Build software that works **beside** each retailer's existing POS/ERP. Keep their system as the transaction source of truth; RetailPilot imports daily aggregates, assesses data quality, estimates demand, recommends purchase quantities and produces unsigned draft purchase orders.

**In scope:** separate tenants/stores; catalog, inventory, supplier parameters, daily sales; stock quality gates; explainable demand forecast; reorder proposal; local dashboard; CSV API connector; seven-day diagnostic and manual review.

**Out of scope:** replacing POS/ERP, payment processing, automatic supplier order placement, loyalty/PII, vendor-specific hardware, facial recognition, camera feeds, final GST billing, robotics, ERP write-back, marketing claims of savings.

## 2. Initial retailer discovery form

Collect from each supermarket owner/authorized manager:

| Field | Required answer |
| --- | --- |
| Authorized business/contact | Legal business name, designated owner, stores in pilot |
| Existing software | POS/ERP vendor, version, export/API capabilities and technical contact |
| Scope | Number of stores, SKUs, suppliers, daily transactions and replenishment schedule |
| Primary problems | Waste, out-of-stocks, overstock, purchasing delays; current cost of each |
| Data contract | Date range, field definitions, clock/timezone, SKU codes and unit conversions |
| Inventory accounting | On-hand, on-order, goods in transit, reserved, damaged and returned stock |
| Supplier rules | Pack size, MOQ, order cutoffs, lead times, delivery calendar and price basis |
| Perishable rules | Expiry lot data, receiving date, shelf life, returns and waste tracking |
| Governance | Who reviews purchase proposals, value limits, audit contacts and data access |
| Pilot design | Baseline period, comparison method, success metrics, retailer sign-off |

Do not ask for customer names, phone numbers, card data, payment tokens or raw CCTV for the initial forecasting pilot.

## 3. Data files and mapping

Required files (templates included in the source package):

1. `products.csv`: `sku,name,supplier,unit_cost,unit_price,lead_days,safety_days,pack_size,min_order_qty,shelf_life_days`.
2. `inventory.csv`: `store_id,sku,on_hand,on_order,snapshot_date`.
3. `sales.csv`: `store_id,sku,date,units`; all completed business days including explicit zero rows.

For each field, confirm what it means in that retailer's POS. Document barcode/unit-of-measure conversion, changes in SKU identity and discontinued products. Historical sales should ideally cover **12 months** to evaluate calendar/seasonal effects; the first local working slice needs 14 complete days per SKU, and the diagnostic needs 21. Ask for 90 days as an initial practical transfer if a full year is unavailable. Data must be corrected for returns, cancellations and duplicate transactions before import.

Additional **pilot measurements** to collect separately until connectors are built: daily stockout duration, expired/wasted units and cost, promotions and holidays, supplier actual lead times and fill rate, open POs, transfer movements, inventory count adjustments. These are critical for valid demand/ROI analysis and cannot yet be inferred by this MVP.

## 4. Safe live-data onboarding

1. Identify a named retailer data owner and obtain written authorization/pilot agreement covering purpose, retention, support and deletion.
2. Share minimum needed sales/inventory datasets. No personal customer or financial credential exports.
3. Record source system, column mappings, units and which dates are complete.
4. Run tenant-specific import tests with a small non-sensitive extract; validate totals against POS and inventory counts.
5. Load more history; reject incomplete SKU/date coverage rather than inventing zero sales.
6. Show suggestions in **shadow mode**—no suppliers are contacted, and no orders are changed.
7. Review weekly with purchaser/manager; record accepted, changed and rejected recommendations and reasons.
8. Export findings to an agreed report. Retain data only for the agreed period and implement deletion at pilot exit.

**Deployment gate:** The current local MVP is a prototype. A real-data pilot must use a controlled, approved device with appropriate access controls and backup, and requires an information-security and legal/privacy review before handling the retailer's confidential data. Never put the unreviewed local HTTP server on the public internet.

**Cloud status (26 October 2026):** The synthetic, read-only demonstration is deployed on Cloudflare Workers with a dedicated D1 database. Only fabricated demo data is publicly accessible. The cloud endpoint is not authorized to receive live customer information until tenant credentials, controls, privacy agreements, backups, and import/reconciliation tests are approved. There is no need to run the synthetic demo on the founder's PC.

## 5. KPI definitions and evaluation

| KPI | Measurement | Guard against misleading conclusions |
| --- | --- | --- |
| Stockout rate | SKU/store days with unavailable items divided by eligible SKU/store days | Track availability independent of low sales |
| Waste cost | Confirmed expired/damaged units × landed unit cost | Exclude supplier-credit recoveries as agreed |
| Forecast error | 7-day holdout WAPE versus a naive or existing baseline | Report eligible SKU coverage and zero-demand cases |
| Inventory turns | Cost of goods sold / average inventory value | Compare like-for-like categories and seasonality |
| Order effort | Purchaser minutes per PO line/order | Measure actual time saved, not clicks |
| Financial ROI | Verified gross margin recovered + waste avoided + labor savings − operating/implementation cost | Avoid double counting and assumptions |

**Pilot evaluation:** Pre-register comparison SKUs/stores, date window and treatment/control selection with the retailers. Start with shadow recommendations, then supervised intervention. Compare changes against matched control products/stores or a justified baseline, adjusting for promotions, calendar, demand changes and supplier disruptions. The pilot owner decides numerical pass thresholds only after baseline quality is known; none are invented here.

## 6. Product acceptance criteria

**Implemented/testable in 0.1:**

- Each of 2–3 retailers has distinct tenant credentials and isolated data.
- One company may contain multiple independently analysed stores.
- CSV batches import atomically; repeat imports update records without double-counting.
- Missing daily sales observations or stale inventory block recommendations.
- Forecast target and pack/MOQ reorder calculations agree with independent worked examples.
- Export is explicitly labeled **DRAFT**, and nothing can trigger a payment/order.
- Local API rejects unauthenticated requests and cross-tenant store lookups.
- A local store manager can review recommendations and backtest diagnostics in the browser.

**Required before a customer-hosted/public SaaS pilot:**

- Formal threat model, tenant isolation audit, secure credential lifecycle, role and approval policies.
- TLS, encrypted backups, tested recovery, monitoring, per-tenant retention/deletion, incident response.
- Production database (e.g., PostgreSQL with row-level protection) and schema migrations.
- Vendor POS adapters with reconciliation against source ledgers, restart/retry and idempotency.
- Forecast evaluation against current store reorder method on real historical data, including stockouts and perishables.
- Operational SLAs and escalation; support and onboarding workflow.

## 7. First 30-day operational checklist (relative to pilot start)

| Period | Deliverable | Owner |
| --- | --- | --- |
| Week 1 | Agreements, owner interview, current POS/export mapping, agreed data policy | Founder + retailers |
| Week 2 | First historical extracts; clean mapping; tenant and store import reconciliation | Technical owner + retailer POS contact |
| Week 3 | Shadow recommendations and baseline evaluation; purchasing reviews | Store buyer + analytics owner |
| Week 4 | Correct mapping errors, quantify false alerts, approve controlled intervention plan | Founder + store management |

Do not claim reductions in waste/stockouts until a controlled live pilot demonstrates them. The larger supermarket OS, computer vision and hardware modules stay outside the first pilot's success gate.
