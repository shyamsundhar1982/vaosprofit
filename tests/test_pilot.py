import csv
import io
import json
import tempfile
import threading
import unittest
from datetime import date, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from retailpilot.core import (
    InvalidData, add_store, backtest, connect, create_tenant, export_drafts,
    import_csv, init_db, recommendations, summary, tenant_from_token,
)
from retailpilot.server import RetailHandler


def csv_text(columns, rows):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(columns)
    w.writerows(rows)
    return out.getvalue()


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "pilot.sqlite3")
        init_db(self.path)
        self.key_a = create_tenant(self.path, "alpha", "Alpha Grocer", "main", "Main")
        self.key_b = create_tenant(self.path, "beta", "Beta Market", "main", "Main")
        self.as_of = date.today() - timedelta(days=1)
        self.product_csv = csv_text(
            ("sku", "name", "supplier", "unit_cost", "unit_price", "lead_days", "safety_days", "pack_size", "min_order_qty", "shelf_life_days"),
            [("SKU1", "Rice", "Vendor", 4, 8, 2, 1, 6, 6, 90)],
        )
        with connect(self.path) as db:
            import_csv(db, "alpha", "products", self.product_csv)
            import_csv(db, "beta", "products", self.product_csv)
            import_csv(db, "alpha", "inventory", csv_text(
                ("store_id", "sku", "on_hand", "on_order", "snapshot_date"),
                [("main", "SKU1", 8, 5, self.as_of.isoformat())]
            ))
            import_csv(db, "beta", "inventory", csv_text(
                ("store_id", "sku", "on_hand", "on_order", "snapshot_date"),
                [("main", "SKU1", 100, 0, self.as_of.isoformat())]
            ))
            import_csv(db, "alpha", "sales", csv_text(
                ("store_id", "sku", "date", "units"),
                [("main", "SKU1", (self.as_of-timedelta(days=n)).isoformat(), 4) for n in range(28)]
            ))
            import_csv(db, "beta", "sales", csv_text(
                ("store_id", "sku", "date", "units"),
                [("main", "SKU1", (self.as_of-timedelta(days=n)).isoformat(), 1) for n in range(28)]
            ))

    def test_forecast_and_pack_reorder(self):
        with connect(self.path) as db:
            rec = recommendations(db, "alpha", "main", self.as_of.isoformat())[0]
            self.assertEqual(rec["status"], "ready")
            self.assertEqual(rec["forecast_daily"], 4)
            self.assertEqual(rec["target_stock"], 40)
            self.assertEqual(rec["suggested_order"], 30)  # 40 - 8 - 5 => pack round 27 to 30
            self.assertEqual(summary([rec])["draft_value"], 120)
            csv_out = export_drafts([rec])
            self.assertIn("SKU1,Rice,Vendor,30,120.0,ready", csv_out)

    def test_backtest_known_constant_demand(self):
        with connect(self.path) as db:
            score = backtest(db, "alpha", "main", self.as_of.isoformat())
            self.assertEqual(score["evaluated_skus"], 1)
            self.assertEqual(score["forecast_wape_pct"], 0)
            self.assertEqual(score["naive_wape_pct"], 0)

    def test_tenant_isolation_and_token_validation(self):
        with connect(self.path) as db:
            self.assertEqual(tenant_from_token(db, self.key_a), "alpha")
            self.assertEqual(tenant_from_token(db, self.key_b), "beta")
            self.assertIsNone(tenant_from_token(db, "wrong"))
            self.assertEqual(recommendations(db, "beta", "main", self.as_of.isoformat())[0]["suggested_order"], 0)
            with self.assertRaisesRegex(InvalidData, "Unknown store"):
                recommendations(db, "alpha", "beta-private", self.as_of.isoformat())

    def test_multiple_stores_are_separate_within_one_retailer(self):
        add_store(self.path, "alpha", "north", "North Branch")
        with connect(self.path) as db:
            northern = recommendations(db, "alpha", "north", self.as_of.isoformat())[0]
            self.assertEqual(northern["status"], "withheld")
            self.assertIsNone(northern["on_hand"])
            self.assertEqual(recommendations(db, "alpha", "main", self.as_of.isoformat())[0]["suggested_order"], 30)

    def test_transactional_import_and_repeat_upsert(self):
        incoming = csv_text(("store_id", "sku", "date", "units"), [
            ("main", "SKU1", self.as_of.isoformat(), 9),
            ("main", "UNKNOWN", self.as_of.isoformat(), 9),
        ])
        with connect(self.path) as db:
            with self.assertRaisesRegex(InvalidData, "CSV row 3"):
                import_csv(db, "alpha", "sales", incoming)
            before = db.execute("SELECT units FROM sales WHERE tenant_id='alpha' AND sku='SKU1' AND day=?", (self.as_of.isoformat(),)).fetchone()[0]
            self.assertEqual(before, 4)
            valid = csv_text(("store_id", "sku", "date", "units"), [("main", "SKU1", self.as_of.isoformat(), 9)])
            import_csv(db, "alpha", "sales", valid)
            import_csv(db, "alpha", "sales", valid)
            rows = db.execute("SELECT COUNT(*) FROM sales WHERE tenant_id='alpha' AND sku='SKU1'").fetchone()[0]
            self.assertEqual(rows, 28)
            self.assertEqual(db.execute("SELECT units FROM sales WHERE tenant_id='alpha' AND day=?", (self.as_of.isoformat(),)).fetchone()[0], 9)

    def test_missing_days_withheld_even_when_sales_zero(self):
        with connect(self.path) as db:
            db.execute("DELETE FROM sales WHERE tenant_id='alpha' AND day=?", ((self.as_of-timedelta(days=1)).isoformat(),))
            db.commit()
            r = recommendations(db, "alpha", "main", self.as_of.isoformat())[0]
            self.assertEqual(r["status"], "withheld")
            self.assertEqual(r["suggested_order"], 0)
            self.assertIn("incomplete_sales_14d", r["flags"])

    def test_stale_stock_and_perishable_review(self):
        with connect(self.path) as db:
            db.execute("UPDATE inventory SET snapshot_date='2023-01-01' WHERE tenant_id='alpha'")
            db.commit()
            self.assertEqual(recommendations(db, "alpha", "main", self.as_of.isoformat())[0]["status"], "withheld")
            db.execute("UPDATE inventory SET snapshot_date=? WHERE tenant_id='alpha'", (self.as_of.isoformat(),))
            db.execute("UPDATE products SET shelf_life_days=2 WHERE tenant_id='alpha'")
            db.commit()
            r = recommendations(db, "alpha", "main", self.as_of.isoformat())[0]
            self.assertEqual(r["status"], "review")
            self.assertIn("perishable_review", r["flags"])

    def test_csv_bad_inputs_and_formula_injection(self):
        with connect(self.path) as db:
            with self.assertRaisesRegex(InvalidData, "Missing columns"):
                import_csv(db, "alpha", "sales", "sku,units\nSKU1,2\n")
            with self.assertRaisesRegex(InvalidData, "extra cells"):
                import_csv(db, "alpha", "sales", "store_id,sku,date,units\nmain,SKU1,2026-10-01,4,unexpected\n")
            with self.assertRaisesRegex(InvalidData, "at least 0"):
                import_csv(db, "alpha", "sales", csv_text(("store_id", "sku", "date", "units"), [("main", "SKU1", self.as_of, -1)]))
            r = recommendations(db, "alpha", "main", self.as_of.isoformat())[0]
            r["name"] = '=HYPERLINK("http://malicious.example")'
            escaped = export_drafts([r])
            self.assertIn("'=HYPERLINK", escaped)

    def test_http_boundary_and_csv_route(self):
        class TestHandler(RetailHandler):
            db_path = self.path

            def log_message(self, *args):
                pass

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        self.addCleanup(httpd.server_close)
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(httpd.shutdown)
        base = f"http://127.0.0.1:{httpd.server_port}"

        def get(path, key=None):
            req = Request(base + path, headers=({"Authorization": "Bearer " + key} if key else {}))
            return urlopen(req, timeout=3)

        with self.assertRaises(HTTPError) as missing:
            get("/api/me")
        self.assertEqual(missing.exception.code, 401)
        with get("/api/me", self.key_a) as response:
            self.assertEqual(json.load(response)["tenant"], "alpha")
        with get("/api/recommendations?as_of="+self.as_of.isoformat(), self.key_b) as response:
            result = json.load(response)
            self.assertEqual(result["items"][0]["suggested_order"], 0)
        with get("/api/drafts.csv?as_of="+self.as_of.isoformat(), self.key_a) as response:
            self.assertIn("SKU1", response.read().decode())
        with self.assertRaises(HTTPError) as invalid:
            get("/api/recommendations?store=other&as_of="+self.as_of.isoformat(), self.key_a)
        self.assertEqual(invalid.exception.code, 400)
        import_body = csv_text(("store_id", "sku", "date", "units"),
                               [("main", "SKU1", self.as_of.isoformat(), 6)]).encode()
        req = Request(base + "/api/import/sales", data=import_body, method="POST", headers={
            "Authorization": "Bearer " + self.key_a, "Content-Type": "text/csv"
        })
        with urlopen(req, timeout=3) as response:
            self.assertEqual(json.load(response)["imported"], 1)
        with connect(self.path) as db:
            self.assertEqual(db.execute("SELECT units FROM sales WHERE tenant_id='alpha' AND day=?",
                                        (self.as_of.isoformat(),)).fetchone()[0], 6)
            self.assertEqual(db.execute("SELECT units FROM sales WHERE tenant_id='beta' AND day=?",
                                        (self.as_of.isoformat(),)).fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
