"""Operator commands for creating isolated tenants and launching a local pilot."""

import argparse
import csv
import io
from datetime import date, timedelta

from .core import add_store, connect, create_tenant, import_csv, init_db
from .server import serve


def demo(db_path: str):
    init_db(db_path)
    for tenant_id, tenant_name in (("pilot-one", "Pilot Grocery One"), ("pilot-two", "Pilot Grocery Two")):
        token = create_tenant(db_path, tenant_id, tenant_name, "main", "Main Store")
        print(f"{tenant_name} - DEMO TOKEN (copy now, only shown once): {token}")
        with connect(db_path) as db:
            products = io.StringIO()
            writer = csv.writer(products)
            writer.writerow(("sku", "name", "supplier", "unit_cost", "unit_price", "lead_days", "safety_days", "pack_size", "min_order_qty", "shelf_life_days"))
            items = [
                ("MILK500", "Milk 500 ml", "Local Dairy", 22, 30, 1, 1, 12, 12, 3),
                ("RICE5K", "Rice 5 kg", "Grain Supplier", 240, 310, 5, 4, 5, 5, 365),
                ("BREAD", "Whole Wheat Bread", "Bakery", 28, 40, 1, 1, 10, 10, 4),
                ("SOAP", "Bath Soap", "FMCG Distributor", 31, 45, 4, 3, 24, 24, 730),
            ]
            writer.writerows(items)
            import_csv(db, tenant_id, "products", products.getvalue())
            day = date.today() - timedelta(days=1)
            inventory = io.StringIO()
            writer = csv.writer(inventory)
            writer.writerow(("store_id", "sku", "on_hand", "on_order", "snapshot_date"))
            for sku, amount in (("MILK500", 15), ("RICE5K", 9), ("BREAD", 8), ("SOAP", 10)):
                writer.writerow(("main", sku, amount, 0, day))
            import_csv(db, tenant_id, "inventory", inventory.getvalue())
            sales = io.StringIO()
            writer = csv.writer(sales)
            writer.writerow(("store_id", "sku", "date", "units"))
            for n in range(42):
                on = day - timedelta(days=n)
                for sku, base in (("MILK500", 8), ("RICE5K", 2), ("BREAD", 5), ("SOAP", 3)):
                    qty = base + (2 if on.weekday() >= 5 else 0) + (n % 3)
                    writer.writerow(("main", sku, on, qty))
            import_csv(db, tenant_id, "sales", sales.getvalue())
    print("Only synthetic records were generated. No live retailer data was accessed.")


def main():
    p = argparse.ArgumentParser(description="RetailPilot offline-safe replenishment MVP")
    p.add_argument("--db", default="retailpilot.sqlite3", help="SQLite pilot database path")
    sub = p.add_subparsers(dest="action", required=True)
    sub.add_parser("init")
    tenant = sub.add_parser("create-tenant")
    for name in ("tenant", "name", "store", "store-name"):
        tenant.add_argument("--" + name, required=True)
    store = sub.add_parser("add-store")
    for name in ("tenant", "store", "name"):
        store.add_argument("--" + name, required=True)
    sub.add_parser("seed-demo")
    server = sub.add_parser("serve")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8766)
    args = p.parse_args()
    if args.action == "init":
        init_db(args.db)
        print("Pilot database initialized")
    elif args.action == "create-tenant":
        init_db(args.db)
        token = create_tenant(args.db, args.tenant, args.name, args.store, args.store_name)
        print(f"Tenant created. API token (copy securely now, only shown once): {token}")
    elif args.action == "add-store":
        add_store(args.db, args.tenant, args.store, args.name)
        print("Store added to tenant")
    elif args.action == "seed-demo":
        demo(args.db)
    else:
        init_db(args.db)
        serve(args.db, args.host, args.port)


if __name__ == "__main__":
    main()
