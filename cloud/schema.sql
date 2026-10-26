-- A dedicated database for RetailPilot. Do not run against existing VAOS or Saathi DBs.
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS tenants (id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tokens (token_hash TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id));
CREATE TABLE IF NOT EXISTS stores (
 tenant_id TEXT NOT NULL REFERENCES tenants(id), id TEXT NOT NULL, name TEXT NOT NULL,
 PRIMARY KEY (tenant_id,id));
CREATE TABLE IF NOT EXISTS products (
 tenant_id TEXT NOT NULL REFERENCES tenants(id), sku TEXT NOT NULL,
 name TEXT NOT NULL, supplier TEXT NOT NULL, unit_cost REAL NOT NULL, unit_price REAL NOT NULL,
 lead_days INTEGER NOT NULL, safety_days INTEGER NOT NULL, pack_size INTEGER NOT NULL,
 min_order_qty INTEGER NOT NULL, shelf_life_days INTEGER NOT NULL,
 PRIMARY KEY (tenant_id,sku));
CREATE TABLE IF NOT EXISTS inventory (
 tenant_id TEXT NOT NULL, store_id TEXT NOT NULL, sku TEXT NOT NULL,
 on_hand INTEGER NOT NULL, on_order INTEGER NOT NULL, snapshot_date TEXT NOT NULL,
 PRIMARY KEY (tenant_id,store_id,sku),
 FOREIGN KEY (tenant_id,store_id) REFERENCES stores(tenant_id,id),
 FOREIGN KEY (tenant_id,sku) REFERENCES products(tenant_id,sku));
CREATE TABLE IF NOT EXISTS sales (
 tenant_id TEXT NOT NULL, store_id TEXT NOT NULL, sku TEXT NOT NULL,
 day TEXT NOT NULL, units INTEGER NOT NULL,
 PRIMARY KEY (tenant_id,store_id,sku,day),
 FOREIGN KEY (tenant_id,store_id) REFERENCES stores(tenant_id,id),
 FOREIGN KEY (tenant_id,sku) REFERENCES products(tenant_id,sku));
CREATE INDEX IF NOT EXISTS sales_recent ON sales (tenant_id,store_id,day);
