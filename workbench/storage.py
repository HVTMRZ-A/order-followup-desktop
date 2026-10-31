import json
import os
import sqlite3
import base64
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
        CREATE TABLE IF NOT EXISTS planbook (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL, source BLOB NOT NULL);
        PRAGMA user_version=1;
        ''')

    def orders(self):
        return [json.loads(r[0]) for r in self.db.execute("SELECT payload FROM orders ORDER BY rowid DESC")]

    def planbook(self):
        row=self.db.execute('SELECT payload FROM planbook WHERE id=1').fetchone()
        return json.loads(row[0]) if row else None

    def planbook_source(self):
        row=self.db.execute('SELECT source FROM planbook WHERE id=1').fetchone()
        return row[0] if row else None

    def save_planbook(self,payload,source=None):
        with self.db:
            if source is None:
                self.db.execute('UPDATE planbook SET payload=? WHERE id=1',(json.dumps(payload,ensure_ascii=False),))
            else:
                self.db.execute('INSERT INTO planbook VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,source=excluded.source',(json.dumps(payload,ensure_ascii=False),source))
                for order in self.orders():
                    order['plan_sync_checked']=False
                    self.db.execute('UPDATE orders SET payload=? WHERE id=?',(json.dumps(order,ensure_ascii=False),order['id']))

    def save_order(self, order, action="保存订单",require_plan_review=True):
        self.save_orders([order], action,require_plan_review=require_plan_review)

    def save_plan_join(self,payload,orders):
        for order in orders:validate_order(order)
        with self.db:
            if payload is not None:
                self.db.execute('UPDATE planbook SET payload=? WHERE id=1',(json.dumps(payload,ensure_ascii=False),))
            for order in orders:
                order['updated_at']=stamp()
                self.db.execute('UPDATE orders SET payload=? WHERE id=?',(json.dumps(order,ensure_ascii=False),order['id']))
                self.db.execute('INSERT INTO audit(at,order_id,action) VALUES(?,?,?)',(stamp(),order['id'],'确认加入计划总表 / 更新待办'))

    def save_orders(self, orders, action="批量导入",require_plan_review=True):
        for order in orders:
            validate_order(order)
        with self.db:
            for order in orders:
                order["updated_at"] = stamp()
                if require_plan_review:order['plan_sync_checked']=False
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
        if self.planbook():content['planbook']={'payload':self.planbook(),'source':base64.b64encode(self.planbook_source()).decode('ascii')}
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
        ledger=content.get('planbook')
        if ledger:
            if not isinstance(ledger['payload'].get('sheets'),list):raise ValueError('计划总表备份格式无效')
            ledger_source=base64.b64decode(ledger['source'],validate=True)
        with self.db:
            self.db.execute("DELETE FROM orders")
            self.db.execute("DELETE FROM daily")
            self.db.execute("DELETE FROM audit")
            self.db.execute('DELETE FROM planbook')
            if ledger:self.db.execute('INSERT INTO planbook VALUES(1,?,?)',(json.dumps(ledger['payload'],ensure_ascii=False),ledger_source))
            for order in content["orders"]:
                self.db.execute("INSERT INTO orders VALUES(?,?,?)", (order["id"], order["number"], json.dumps(order, ensure_ascii=False)))
            for day, payload in content["daily"]:
                self.db.execute("INSERT INTO daily VALUES(?,?)", (day, json.dumps(payload, ensure_ascii=False)))
            for row in content.get("audit", []):
                self.db.execute("INSERT INTO audit(at,order_id,action) VALUES(?,?,?)", row)
        return backup

