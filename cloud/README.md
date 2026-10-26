# Cloud deployment: GitHub + Cloudflare Workers + D1

`vaosprofit` hosts RetailPilot independently of SPARK, VAOS and VYNDI OS. The original Python application remains in the repo as a verified local reference implementation; **the cloud runtime is JavaScript in `cloud/`** and does not require anyone's PC to stay online.

**Current synthetic demonstration:** https://vaosprofit-retailpilot.vayushastr.workers.dev/ (use **Explore synthetic demo**). This cloud endpoint has no customer data. The pilot's D1 database is created and schema-initialized, but live retailer tenant credentials/data have not been onboarded.

## Design

- Worker returns the same review dashboard plus authenticated JSON/CSV API.
- D1 stores retailer-scoped products, stock, daily sales and token hashes.
- A public synthetic demo can be opened without an account. Demo cannot import files or place orders.
- Live retailer credentials are provisioned separately; never hardcode keys in Git.
- Daily sales CSVs must include explicit zeros, and stock snapshots must be current.
- Each file is uploaded in small, server-validated chunks. Automatic purchasing and payments are not implemented.

## Developer workflow

```sh
node cloud/build.mjs
node --check cloud/dist/worker.mjs
node --test tests/test_cloud.mjs
```

`build.mjs` packages the dashboard and two cloud modules into a single Worker module. `dist/` is generated and ignored by Git.

Cloud deployment uses a **dedicated** D1 database initialized from `cloud/schema.sql`, a Worker script with binding `DB`, and workers.dev routing. Never apply this SQL to an existing VAOS, Saathi or VYNDI database. Do not push tenant data or API tokens into the repository.

The included `wrangler.jsonc` references that dedicated D1 database. GitHub Actions runs tests and build checks, but **does not deploy on push**; Cloudflare publishing still requires an authorized deployment operation and an operator's live acceptance.

## Limitations and acceptance boundary

This is a cloud pilot, **not an audited commercial multi-tenant SaaS**. Cloudflare D1 Free tier has daily read/write limits and requests will fail if limits are reached. Production use still requires tenant-security review, stronger credential management and authorization roles, rate limiting, detailed audit logs, backups and restore rehearsals, data-retention/deletion policy, contractual onboarding and source-POS reconciliation.

Cloud script and Python reference are independently tested with matching worked examples. Changes to the formula must update both and their tests until the Python reference is retired.
