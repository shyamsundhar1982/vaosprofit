"""Tenant-scoped storage, validation and deterministic replenishment logic.

This is a pilot engine, not an accounting or purchase execution system.
Daily sales CSVs must include explicit zero-sales days for each product.
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import math
import secrets
import sqlite3
from datetime import date, timedelta
from pathlib import Path


class InvalidData(ValueError):
    pass


SCHEMAS = {
    "products": ("sku", "name", "supplier", "unit_cost", "unit_price", "lead_days", "safety_days", "pack_size", "min_order_qty", "shelf_life_days"),
    "inventory": ("store_id", "sku", "on_hand", "on_order", "snapshot_date"),
    "sales": ("store_id", "sku", "date", "units"),
}


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def init_db(db_path: str | Path) -> None:
    with connect(db_path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS tenants (
          id TEXT PRIMARY KEY, name TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tokens (
          token_hash TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id)
        );
        CREATE TABLE IF NOT EXISTS stores (
          tenant_id TEXT NOT NULL REFERENCES tenants(id),
          id TEXT NOT NULL, name TEXT NOT NULL,
          PRIMARY KEY (tenant_id, id)
        );
        CREATE TABLE IF NOT EXISTS products (
          tenant_id TEXT NOT NULL REFERENCES tenants(id),
          sku TEXT NOT NULL, name TEXT NOT NULL, supplier TEXT NOT NULL,
          unit_cost REAL NOT NULL, unit_price REAL NOT NULL,
          lead_days INTEGER NOT NULL, safety_days INTEGER NOT NULL,
          pack_size INTEGER NOT NULL, min_order_qty INTEGER NOT NULL,
          shelf_life_days INTEGER NOT NULL,
          PRIMARY KEY (tenant_id, sku)
        );
        CREATE TABLE IF NOT EXISTS inventory (
          tenant_id TEXT NOT NULL, store_id TEXT NOT NULL, sku TEXT NOT NULL,
          on_hand INTEGER NOT NULL, on_order INTEGER NOT NULL,
          snapshot_date TEXT NOT NULL,
          PRIMARY KEY (tenant_id, store_id, sku),
          FOREIGN KEY (tenant_id, store_id) REFERENCES stores(tenant_id, id),
          FOREIGN KEY (tenant_id, sku) REFERENCES products(tenant_id, sku)
        );
        CREATE TABLE IF NOT EXISTS sales (
          tenant_id TEXT NOT NULL, store_id TEXT NOT NULL, sku TEXT NOT NULL,
          day TEXT NOT NULL, units INTEGER NOT NULL,
          PRIMARY KEY (tenant_id, store_id, sku, day),
          FOREIGN KEY (tenant_id, store_id) REFERENCES stores(tenant_id, id),
          FOREIGN KEY (tenant_id, sku) REFERENCES products(tenant_id, sku)
        );
        CREATE INDEX IF NOT EXISTS sales_recent ON sales(tenant_id, store_id, day);
        """)


def create_tenant(db_path: str | Path, tenant_id: str, name: str, store_id: str, store_name: str) -> str:
    if not all((tenant_id.strip(), name.strip(), store_id.strip(), store_name.strip())):
        raise InvalidData("Tenant and store identifiers/names are required")
    key = secrets.token_urlsafe(32)
    digest = hashlib.sha256(key.encode()).hexdigest()
    with connect(db_path) as db:
        db.execute("INSERT INTO tenants VALUES (?, ?)", (tenant_id, name))
        db.execute("INSERT INTO stores VALUES (?, ?, ?)", (tenant_id, store_id, store_name))
        db.execute("INSERT INTO tokens VALUES (?, ?)", (digest, tenant_id))
    return key


def add_store(db_path: str | Path, tenant_id: str, store_id: str, store_name: str) -> None:
    if not all((tenant_id.strip(), store_id.strip(), store_name.strip())):
        raise InvalidData("Store and tenant identifiers/names are required")
    with connect(db_path) as db:
        db.execute("INSERT INTO stores VALUES (?,?,?)", (tenant_id, store_id, store_name))


def tenant_from_token(db: sqlite3.Connection, token: str) -> str | None:
    if not token or len(token) > 256:
        return None
    digest = hashlib.sha256(token.encode()).hexdigest()
    # Digest is indexed; hmac prevents timing comparisons against supplied values.
    row = db.execute("SELECT token_hash, tenant_id FROM tokens WHERE token_hash=?", (digest,)).fetchone()
    return row["tenant_id"] if row and hmac.compare_digest(row["token_hash"], digest) else None


def stores(db: sqlite3.Connection, tenant_id: str) -> list[dict]:
    return [dict(row) for row in db.execute("SELECT id, name FROM stores WHERE tenant_id=? ORDER BY id", (tenant_id,))]


def ensure_store(db: sqlite3.Connection, tenant_id: str, store_id: str) -> None:
    row = db.execute("SELECT 1 FROM stores WHERE tenant_id=? AND id=?", (tenant_id, store_id)).fetchone()
    if row is None:
        raise InvalidData("Unknown store for this tenant")


def _number(raw: str, field: str, *, integer: bool = False, minimum: float = 0) -> float | int:
    try:
        value = int(raw) if integer else float(raw)
    except (ValueError, TypeError) as exc:
        raise InvalidData(f"{field} must be a valid number") from exc
    if not math.isfinite(value) or value < minimum:
        raise InvalidData(f"{field} must be at least {minimum}")
    return value


def _date(raw: str, field: str) -> str:
    try:
        parsed = date.fromisoformat(raw)
        if parsed.isoformat() != raw:
            raise ValueError("Date is not in ISO format")
        return parsed.isoformat()
    except (TypeError, ValueError) as exc:
        raise InvalidData(f"{field} must be YYYY-MM-DD") from exc


def import_csv(db: sqlite3.Connection, tenant_id: str, kind: str, payload: str) -> int:
    if kind not in SCHEMAS:
        raise InvalidData("Unknown import type")
    if not payload.strip():
        raise InvalidData("CSV is empty")
    try:
        reader = csv.DictReader(io.StringIO(payload, newline=""), strict=True)
        if not reader.fieldnames or None in reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise InvalidData("CSV has no header or duplicate columns")
        missing = set(SCHEMAS[kind]) - set(reader.fieldnames)
        if missing:
            raise InvalidData("Missing columns: " + ", ".join(sorted(missing)))
        records = list(reader)
    except csv.Error as exc:
        raise InvalidData(f"Malformed CSV: {exc}") from exc
    if not records:
        raise InvalidData("CSV has no data rows")
    if len(records) > 30000:
        raise InvalidData("Import limit is 30,000 rows per batch; split larger exports")
    try:
        # Transaction is all-or-nothing, including ownership and data validation.
        with db:
            for i, row in enumerate(records, 2):
                try:
                    if None in row or any(v is None for v in row.values()):
                        raise InvalidData("Row has missing or extra cells")
                    if kind == "products":
                        sku, name, supplier = (row[k].strip() for k in ("sku", "name", "supplier"))
                        if not sku or not name or not supplier:
                            raise InvalidData("sku, name and supplier cannot be blank")
                        vals = (
                            _number(row["unit_cost"], "unit_cost"),
                            _number(row["unit_price"], "unit_price"),
                            _number(row["lead_days"], "lead_days", integer=True),
                            _number(row["safety_days"], "safety_days", integer=True),
                            _number(row["pack_size"], "pack_size", integer=True, minimum=1),
                            _number(row["min_order_qty"], "min_order_qty", integer=True),
                            _number(row["shelf_life_days"], "shelf_life_days", integer=True),
                        )
                        db.execute("""INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?,?,?)
                          ON CONFLICT(tenant_id,sku) DO UPDATE SET
                          name=excluded.name, supplier=excluded.supplier,
                          unit_cost=excluded.unit_cost, unit_price=excluded.unit_price,
                          lead_days=excluded.lead_days, safety_days=excluded.safety_days,
                          pack_size=excluded.pack_size, min_order_qty=excluded.min_order_qty,
                          shelf_life_days=excluded.shelf_life_days""", (tenant_id, sku, name, supplier, *vals))
                    elif kind == "inventory":
                        store_id, sku = row["store_id"].strip(), row["sku"].strip()
                        ensure_store(db, tenant_id, store_id)
                        db.execute("""INSERT INTO inventory VALUES (?,?,?,?,?,?)
                          ON CONFLICT(tenant_id,store_id,sku) DO UPDATE SET
                          on_hand=excluded.on_hand, on_order=excluded.on_order,
                          snapshot_date=excluded.snapshot_date""", (
                            tenant_id, store_id, sku,
                            _number(row["on_hand"], "on_hand", integer=True),
                            _number(row["on_order"], "on_order", integer=True),
                            _date(row["snapshot_date"], "snapshot_date"),
                        ))
                    else:
                        store_id, sku = row["store_id"].strip(), row["sku"].strip()
                        ensure_store(db, tenant_id, store_id)
                        db.execute("""INSERT INTO sales VALUES (?,?,?,?,?)
                          ON CONFLICT(tenant_id,store_id,sku,day) DO UPDATE SET
                          units=excluded.units""", (
                            tenant_id, store_id, sku, _date(row["date"], "date"),
                            _number(row["units"], "units", integer=True),
                        ))
                except (InvalidData, sqlite3.IntegrityError) as exc:
                    raise InvalidData(f"CSV row {i}: {exc}") from exc
    except sqlite3.IntegrityError as exc:
        raise InvalidData(f"Import failed: {exc}") from exc
    return len(records)


def _round_pack(qty: int, pack_size: int) -> int:
    return math.ceil(qty / pack_size) * pack_size if qty > 0 else 0


def recommendations(db: sqlite3.Connection, tenant_id: str, store_id: str, as_of: str, review_days: int = 7) -> list[dict]:
    ensure_store(db, tenant_id, store_id)
    as_of_day = date.fromisoformat(_date(as_of, "as_of"))
    if not 1 <= review_days <= 30:
        raise InvalidData("review_days must be between 1 and 30")
    start = (as_of_day - timedelta(days=27)).isoformat()
    rows = db.execute("""SELECT p.*, i.on_hand, i.on_order, i.snapshot_date
        FROM products p LEFT JOIN inventory i
          ON p.tenant_id=i.tenant_id AND p.sku=i.sku AND i.store_id=?
        WHERE p.tenant_id=? ORDER BY p.sku""", (store_id, tenant_id)).fetchall()
    sales = db.execute("""SELECT sku, day, units FROM sales
        WHERE tenant_id=? AND store_id=? AND day BETWEEN ? AND ?""",
        (tenant_id, store_id, start, as_of_day.isoformat())).fetchall()
    by_sku: dict[str, dict[str, int]] = {}
    for sale in sales:
        by_sku.setdefault(sale["sku"], {})[sale["day"]] = sale["units"]
    result = []
    for row in rows:
        item = dict(row)
        history = by_sku.get(item["sku"], {})
        last14 = [(as_of_day - timedelta(days=n)).isoformat() for n in range(14)]
        last28 = [(as_of_day - timedelta(days=n)).isoformat() for n in range(28)]
        recent_days = len([day for day in last14 if day in history])
        flags = []
        if recent_days != 14:
            flags.append("incomplete_sales_14d")
        if item["snapshot_date"] is None:
            flags.append("missing_inventory")
        elif abs((as_of_day - date.fromisoformat(item["snapshot_date"])).days) > 1:
            flags.append("stale_inventory")
        if as_of_day > date.today():
            flags.append("future_as_of")
        eligible = not flags
        forecast = None
        order = 0
        target = None
        days_of_cover = None
        if eligible:
            mean7 = sum(history[day] for day in last14[:7]) / 7
            length = 28 if all(day in history for day in last28) else 14
            window = last28 if length == 28 else last14
            avg = sum(history[day] for day in window) / length
            forecast = round(0.6 * mean7 + 0.4 * avg, 3)
            target = math.ceil(forecast * (item["lead_days"] + item["safety_days"] + review_days))
            deficit = max(0, target - item["on_hand"] - item["on_order"])
            if deficit:
                order = _round_pack(max(deficit, item["min_order_qty"]), item["pack_size"])
            days_of_cover = round((item["on_hand"] + item["on_order"]) / forecast, 1) if forecast else None
            if item["shelf_life_days"] and item["shelf_life_days"] < item["lead_days"] + item["safety_days"] + review_days:
                flags.append("perishable_review")
            if item["on_hand"] == 0:
                flags.append("possible_censored_demand")
            if length < 28:
                flags.append("limited_history")
        status = "withheld" if not eligible else "review" if flags else "ready"
        result.append({
            "sku": item["sku"], "name": item["name"], "supplier": item["supplier"],
            "on_hand": item["on_hand"], "on_order": item["on_order"],
            "unit_cost": item["unit_cost"], "forecast_daily": forecast,
            "target_stock": target, "days_of_cover": days_of_cover,
            "suggested_order": order, "estimated_order_value": round(order * item["unit_cost"], 2),
            "status": status, "flags": flags,
        })
    result.sort(key=lambda r: (r["status"] == "withheld", -r["suggested_order"], r["sku"]))
    return result


def summary(items: list[dict]) -> dict:
    return {
        "skus": len(items),
        "actionable": sum(x["status"] != "withheld" for x in items),
        "withheld": sum(x["status"] == "withheld" for x in items),
        "review_needed": sum(x["status"] == "review" for x in items),
        "order_lines": sum(x["suggested_order"] > 0 for x in items),
        "draft_value": round(sum(x["estimated_order_value"] for x in items), 2),
    }


def export_drafts(items: list[dict]) -> str:
    # Neutralize spreadsheet formula injection from retailer-provided text fields.
    def safe(value: object) -> object:
        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
            return "'" + value
        return value

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(("sku", "product", "supplier", "suggested_units", "estimated_value", "review_status", "flags"))
    for r in items:
        if r["suggested_order"] > 0 and r["status"] != "withheld":
            writer.writerow((safe(r["sku"]), safe(r["name"]), safe(r["supplier"]), r["suggested_order"],
                             r["estimated_order_value"], r["status"], safe("|".join(r["flags"]))))
    return buffer.getvalue()


def backtest(db: sqlite3.Connection, tenant_id: str, store_id: str, as_of: str) -> dict:
    """Walk-forward holdout: forecast last 7 complete days from prior 14 days.

    Metrics are diagnostic, not proof of commercial ROI.
    """
    ensure_store(db, tenant_id, store_id)
    as_day = date.fromisoformat(_date(as_of, "as_of"))
    start = (as_day - timedelta(days=20)).isoformat()
    data = db.execute("SELECT sku,day,units FROM sales WHERE tenant_id=? AND store_id=? AND day BETWEEN ? AND ?",
                      (tenant_id, store_id, start, as_of)).fetchall()
    groups: dict[str, dict[str, int]] = {}
    for row in data:
        groups.setdefault(row["sku"], {})[row["day"]] = row["units"]
    actual_total = error_total = baseline_error = 0.0
    evaluated = 0
    for sku, observed in groups.items():
        dates = [(as_day - timedelta(days=n)).isoformat() for n in range(21)]
        if not all(day in observed for day in dates):
            continue
        holdout = sum(observed[d] for d in dates[:7])
        prior14 = [observed[d] for d in dates[7:]]
        forecast = 7 * (0.6 * sum(prior14[:7]) / 7 + 0.4 * sum(prior14) / 14)
        naive = 7 * (sum(prior14[:7]) / 7)
        actual_total += holdout
        error_total += abs(holdout - forecast)
        baseline_error += abs(holdout - naive)
        evaluated += 1
    return {
        "evaluated_skus": evaluated,
        "holdout_days": 7,
        "forecast_wape_pct": round(100 * error_total / actual_total, 2) if actual_total else None,
        "naive_wape_pct": round(100 * baseline_error / actual_total, 2) if actual_total else None,
        "warning": "Requires 21 complete daily records per SKU; WAPE does not establish commercial ROI.",
    }
