import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from .domain import stamp, validate_order


def data_dir():
    path = Path(os.environ.get("ORDER_WORKBENCH_DATA", Path(os.environ.get("LOCALAPPDATA", Path.home())) / "OrderFollowupDesktop"))
    path.mkdir(parents=True, exist_ok=True)
    return path


class Store:
    def __init__(self, path=None):
        self.path = Path(path) if path else data_dir() / "workbench.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, number TEXT UNIQUE NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS daily (day TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, at TEXT, order_id TEXT, action TEXT);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        PRAGMA user_version=1;
        ''')

    def orders(self):
        return [json.loads(r[0]) for r in self.db.execute("SELECT payload FROM orders ORDER BY rowid DESC")]

    def save_order(self, order, action="保存订单"):
        self.save_orders([order], action)

    def save_orders(self, orders, action="批量导入"):
        for order in orders:
            validate_order(order)
        with self.db:
            for order in orders:
                order["updated_at"] = stamp()
                self.db.execute("INSERT INTO orders VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET number=excluded.number,payload=excluded.payload",
                                (order["id"], order["number"], json.dumps(order, ensure_ascii=False)))
                self.db.execute("INSERT INTO audit(at,order_id,action) VALUES(?,?,?)", (stamp(), order["id"], action))

    def daily(self, day):
        row = self.db.execute("SELECT payload FROM daily WHERE day=?", (day,)).fetchone()
        return json.loads(row[0]) if row else {}

    def daily_all(self):
        return [(r[0], json.loads(r[1])) for r in self.db.execute("SELECT day,payload FROM daily ORDER BY day DESC")]

    def save_daily(self, day, payload):
        with self.db:
            self.db.execute("INSERT INTO daily VALUES(?,?) ON CONFLICT(day) DO UPDATE SET payload=excluded.payload", (day, json.dumps(payload, ensure_ascii=False)))

    def history(self, order_id):
        return list(self.db.execute("SELECT at,action FROM audit WHERE order_id=? ORDER BY id DESC LIMIT 100", (order_id,)))

    def get(self, key, default=""):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set(self, key, value):
        with self.db:
            self.db.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def backup(self, target=None):
        target = Path(target) if target else self.path.parent / "backups" / f"workbench-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite3"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.resolve() == self.path.resolve():
            raise ValueError("备份文件不能覆盖正在使用的数据库")
        with sqlite3.connect(target) as dest:
            self.db.backup(dest)
        return target

    def export_json(self, target):
        content = {"format": "order-followup-backup-v1", "orders": self.orders(), "daily": self.daily_all(),
                   "audit": list(self.db.execute("SELECT at,order_id,action FROM audit"))}
        Path(target).write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")

    def restore_json(self, target):
        content = json.loads(Path(target).read_text(encoding="utf-8"))
        if content.get("format") != "order-followup-backup-v1":
            raise ValueError("不是本程序的备份文件")
        seen_ids, seen_numbers = set(), set()
        for order in content["orders"]:
            validate_order(order)
            if order["id"] in seen_ids or order["number"] in seen_numbers:
                raise ValueError("备份中存在重复订单")
            seen_ids.add(order["id"]); seen_numbers.add(order["number"])
        for day, payload in content["daily"]:
            datetime.fromisoformat(day)
            if not isinstance(payload, dict):
                raise ValueError("每日记录格式无效")
        backup = self.backup()
        with self.db:
            self.db.execute("DELETE FROM orders")
            self.db.execute("DELETE FROM daily")
            self.db.execute("DELETE FROM audit")
            for order in content["orders"]:
                self.db.execute("INSERT INTO orders VALUES(?,?,?)", (order["id"], order["number"], json.dumps(order, ensure_ascii=False)))
            for day, payload in content["daily"]:
                self.db.execute("INSERT INTO daily VALUES(?,?)", (day, json.dumps(payload, ensure_ascii=False)))
            for row in content.get("audit", []):
                self.db.execute("INSERT INTO audit(at,order_id,action) VALUES(?,?,?)", row)
        return backup

