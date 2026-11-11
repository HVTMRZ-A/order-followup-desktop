import json
import os
import sqlite3
import base64
import copy
from datetime import datetime
from pathlib import Path
from .domain import stamp, validate_order, uid


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
        CREATE TABLE IF NOT EXISTS order_trash (id TEXT PRIMARY KEY, deleted_at TEXT NOT NULL, payload TEXT NOT NULL, restored_at TEXT);
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
                self.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('planbook_revision',uid()))
                self.db.execute('INSERT INTO planbook VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,source=excluded.source',(json.dumps(payload,ensure_ascii=False),source))
                for order in self.orders():
                    order['plan_sync_checked']=False
                    self.db.execute('UPDATE orders SET payload=? WHERE id=?',(json.dumps(order,ensure_ascii=False),order['id']))
            self._mark_plan_saved()

    def _mark_plan_saved(self):
        self.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('planbook_saved_at',stamp()))

    def save_order(self, order, action="保存订单",require_plan_review=True,clear_removed_plan_ids=()):
        self.save_orders([order], action,require_plan_review=require_plan_review,clear_removed_plan_ids=clear_removed_plan_ids)

    def save_plan_join(self,payload,orders):
        for order in orders:validate_order(order)
        with self.db:
            if payload is not None:
                self.db.execute('UPDATE planbook SET payload=? WHERE id=1',(json.dumps(payload,ensure_ascii=False),))
                self._mark_plan_saved()
            for order in orders:
                order['updated_at']=stamp()
                self.db.execute('UPDATE orders SET payload=? WHERE id=?',(json.dumps(order,ensure_ascii=False),order['id']))
                self.db.execute('INSERT INTO audit(at,order_id,action) VALUES(?,?,?)',(stamp(),order['id'],'确认加入计划总表 / 更新待办'))

    def save_plan_edit(self, payload, orders=(), action='计划总表直接修改', daily=None):
        from .order_changes import refresh_overrides
        for order in orders:
            validate_order(order)
            previous=self.db.execute('SELECT payload FROM orders WHERE id=?',(order['id'],)).fetchone()
            if previous is None:raise ValueError('关联订单已不存在，请刷新后重试。')
            refresh_overrides(json.loads(previous[0]),order)
            order['plan_sync_checked']=False
            order['updated_at']=stamp()
        with self.db:
            self.db.execute('UPDATE planbook SET payload=? WHERE id=1',(json.dumps(payload,ensure_ascii=False),))
            self._mark_plan_saved()
            for order in orders:
                self.db.execute('UPDATE orders SET number=?,payload=? WHERE id=?',
                                (order['number'],json.dumps(order,ensure_ascii=False),order['id']))
                self.db.execute('INSERT INTO audit(at,order_id,action) VALUES(?,?,?)',(stamp(),order['id'],action))
            for day, records in (daily or {}).items():
                self.db.execute('INSERT OR REPLACE INTO daily VALUES(?,?)',(day,json.dumps(records,ensure_ascii=False)))

    def table_format(self,name):return json.loads(self.get('table_format_'+name,'{}'))

    def save_table_format(self,name,payload):self.set('table_format_'+name,json.dumps(payload,ensure_ascii=False))

    def apply_history(self, orders, plan, daily, action, views=None):
        from .order_changes import refresh_overrides
        with self.db:
            for order in orders:
                previous=self.db.execute('SELECT payload FROM orders WHERE id=?',(order['id'],)).fetchone()
                if previous is None:raise ValueError('订单已移除，撤销未执行。')
                refresh_overrides(json.loads(previous[0]),order)
                self.db.execute('UPDATE orders SET number=?,payload=? WHERE id=?',(order['number'],json.dumps(order,ensure_ascii=False),order['id']))
                self.db.execute('INSERT INTO audit(at,order_id,action) VALUES(?,?,?)',(stamp(),order['id'],action))
            if plan is not None:
                self.db.execute('UPDATE planbook SET payload=? WHERE id=1',(json.dumps(plan,ensure_ascii=False),));self._mark_plan_saved()
            for day, records in daily.items():
                self.db.execute('INSERT OR REPLACE INTO daily VALUES(?,?)',(day,json.dumps(records,ensure_ascii=False)))
            for name,payload in (views or {}).items():
                self.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('table_format_'+name,json.dumps(payload,ensure_ascii=False)))
            if not orders:self.db.execute('INSERT INTO audit(at,order_id,action) VALUES(?,?,?)',(stamp(),None,action))

    def save_orders(self, orders, action="批量导入",require_plan_review=True,clear_removed_plan_ids=()):
        for order in orders:
            validate_order(order)
        removals = []
        plan = self.planbook()
        from .order_changes import detach_plan
        for order in orders:
            previous = self.db.execute('SELECT payload FROM orders WHERE id=?', (order['id'],)).fetchone()
            if not previous:
                continue
            previous = json.loads(previous[0])
            kept = {i['id'] for i in order['items']}
            for item in previous['items']:
                if item['id'] not in kept:
                    clear = item['id'] in clear_removed_plan_ids
                    removals.append(dict(kind='item', order=previous, item_id=item['id'], clear_plan_rows=clear))
                    plan = detach_plan(plan, order['id'], {item['id']}, clear)
        if removals:
            backup = str(self.backup())
        with self.db:
            for snapshot in removals:
                snapshot['backup'] = backup
                self.db.execute('INSERT INTO order_trash VALUES(?,?,?,NULL)', (uid(), stamp(), json.dumps(snapshot, ensure_ascii=False)))
                model = next(i['model'] for i in snapshot['order']['items'] if i['id'] == snapshot['item_id'])
                self.db.execute('INSERT INTO audit(at,order_id,action) VALUES(?,?,?)',
                                (stamp(), snapshot['order']['id'], '编辑订单时移除型号至回收站：' + model))
            if removals and plan is not None:
                self.db.execute('UPDATE planbook SET payload=? WHERE id=1', (json.dumps(plan, ensure_ascii=False),))
                self._mark_plan_saved()
            for order in orders:
                previous = self.db.execute('SELECT payload FROM orders WHERE id=?', (order['id'],)).fetchone()
                if previous:
                    from .order_changes import refresh_overrides
                    refresh_overrides(json.loads(previous[0]), order)
                order["updated_at"] = stamp()
                if require_plan_review:order['plan_sync_checked']=False
                self.db.execute("INSERT INTO orders VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET number=excluded.number,payload=excluded.payload",
                                (order["id"], order["number"], json.dumps(order, ensure_ascii=False)))
                self.db.execute("INSERT INTO audit(at,order_id,action) VALUES(?,?,?)", (stamp(), order["id"], action))

    def trash(self):
        return [dict(id=r[0], deleted_at=r[1], **json.loads(r[2])) for r in self.db.execute(
            'SELECT id,deleted_at,payload FROM order_trash WHERE restored_at IS NULL ORDER BY rowid DESC')]

    def delete_order(self, order_id, item_id=None, clear_plan_rows=False):
        """订单或型号移入回收站；关联修改与删除在同一事务内完成。"""
        from .order_changes import remove_model, detach_plan
        order = next((o for o in self.orders() if o['id'] == order_id), None)
        if order is None:
            raise ValueError('所选订单已不存在，请刷新后重试。')
        remaining = remove_model(order, item_id) if item_id else None
        item_ids = {item_id} if item_id else {i['id'] for i in order['items']}
        payload = detach_plan(self.planbook(), order_id, item_ids, clear_plan_rows)
        snapshot = dict(kind='item' if item_id else 'order', order=order, item_id=item_id,
                        clear_plan_rows=bool(clear_plan_rows))
        backup = self.backup()
        snapshot['backup'] = str(backup)
        identity = uid()
        with self.db:
            self.db.execute('INSERT INTO order_trash VALUES(?,?,?,NULL)',
                            (identity, stamp(), json.dumps(snapshot, ensure_ascii=False)))
            if remaining:
                remaining['updated_at'] = stamp()
                self.db.execute('UPDATE orders SET payload=? WHERE id=?', (json.dumps(remaining, ensure_ascii=False), order_id))
            else:
                self.db.execute('DELETE FROM orders WHERE id=?', (order_id,))
                for day, records in self.daily_all():
                    changed = False
                    for record in records.values():
                        if order_id in record.get('order_ids', []):
                            record['order_ids'] = [i for i in record['order_ids'] if i != order_id]
                            changed = True
                    if changed:
                        self.db.execute('UPDATE daily SET payload=? WHERE day=?', (json.dumps(records, ensure_ascii=False), day))
            if payload is not None:
                self.db.execute('UPDATE planbook SET payload=? WHERE id=1', (json.dumps(payload, ensure_ascii=False),))
                self._mark_plan_saved()
            model = next((i['model'] for i in order['items'] if i['id'] == item_id), '')
            action = f'移入回收站：型号 {model}' if item_id else '整单移入回收站'
            if clear_plan_rows:
                action += '；清空关联计划行输入值（保留公式、行号和格式）'
            self.db.execute('INSERT INTO audit(at,order_id,action) VALUES(?,?,?)', (stamp(), order_id, action))
        return identity

    def restore_deleted(self, identity):
        snapshot = next((r for r in self.trash() if r['id'] == identity), None)
        if snapshot is None:
            raise ValueError('此记录已恢复或不存在，请刷新回收站。')
        original = snapshot['order']
        current = next((o for o in self.orders() if o['id'] == original['id']), None)
        if snapshot['kind'] == 'order':
            if current or any(o['number'] == original['number'] for o in self.orders()):
                raise ValueError('已有相同订单号或订单记录。请先编辑现有订单号，避免覆盖当前数据。')
            restored = copy.deepcopy(original)
        else:
            if current is None:
                raise ValueError('所属订单已删除，请先从回收站恢复整单，再恢复此型号。')
            restored = copy.deepcopy(current)
            item_id = snapshot['item_id']
            item = next(i for i in original['items'] if i['id'] == item_id)
            if any(i['id'] == item_id or i['model'] == item['model'] for i in restored['items']):
                raise ValueError('订单中已有相同型号，不能覆盖。请先编辑现有型号。')
            index = next(n for n, i in enumerate(original['items']) if i['id'] == item_id)
            restored['items'].insert(min(index, len(restored['items'])), copy.deepcopy(item))
            restored.setdefault('materials', []).extend(copy.deepcopy([m for m in original.get('materials', []) if m['item_id'] == item_id]))
            prefix = f"{original['id']}:{item_id}:"
            restored.setdefault('plan_overrides', {}).update(copy.deepcopy({k: v for k, v in original.get('plan_overrides', {}).items() if k.startswith(prefix)}))
        restored['plan_sync_checked'] = False
        restored['updated_at'] = stamp()
        validate_order(restored)
        self.backup()
        with self.db:
            self.db.execute('INSERT INTO orders VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',
                            (restored['id'], restored['number'], json.dumps(restored, ensure_ascii=False)))
            self.db.execute('UPDATE order_trash SET restored_at=? WHERE id=?', (stamp(), identity))
            self.db.execute('INSERT INTO audit(at,order_id,action) VALUES(?,?,?)',
                            (stamp(), restored['id'], '从回收站恢复；计划行及每日关联待重新确认'))
        return restored

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
                   "table_formats":{name:self.table_format(name) for name in ('orders','materials')},
                   "audit": list(self.db.execute("SELECT at,order_id,action FROM audit")),
                   "order_trash": list(self.db.execute('SELECT id,deleted_at,payload,restored_at FROM order_trash'))}
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
        trash = content.get('order_trash', [])
        trash_ids = set()
        for identity, deleted_at, payload, restored_at in trash:
            snapshot = json.loads(payload)
            validate_order(snapshot['order'])
            datetime.fromisoformat(deleted_at)
            if restored_at:
                datetime.fromisoformat(restored_at)
            if identity in trash_ids or snapshot['kind'] not in ('item', 'order'):
                raise ValueError('回收站记录格式无效')
            if snapshot['kind'] == 'item' and not any(i['id'] == snapshot['item_id'] for i in snapshot['order']['items']):
                raise ValueError('回收站型号记录格式无效')
            trash_ids.add(identity)
        backup = self.backup()
        ledger=content.get('planbook')
        if ledger:
            if not isinstance(ledger['payload'].get('sheets'),list):raise ValueError('计划总表备份格式无效')
            ledger_source=base64.b64decode(ledger['source'],validate=True)
        with self.db:
            self.db.execute("DELETE FROM orders")
            self.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('data_revision',uid()))
            for name in ('orders','materials'):
                self.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('table_format_'+name,json.dumps(content.get('table_formats',{}).get(name,{}),ensure_ascii=False)))
            self.db.execute("DELETE FROM daily")
            self.db.execute("DELETE FROM audit")
            self.db.execute('DELETE FROM planbook')
            self.db.execute('DELETE FROM order_trash')
            if ledger:
                self.db.execute('INSERT INTO planbook VALUES(1,?,?)',(json.dumps(ledger['payload'],ensure_ascii=False),ledger_source));self._mark_plan_saved()
            else:self.db.execute('DELETE FROM settings WHERE key=?',('planbook_saved_at',))
            for order in content["orders"]:
                self.db.execute("INSERT INTO orders VALUES(?,?,?)", (order["id"], order["number"], json.dumps(order, ensure_ascii=False)))
            for day, payload in content["daily"]:
                self.db.execute("INSERT INTO daily VALUES(?,?)", (day, json.dumps(payload, ensure_ascii=False)))
            for row in content.get("audit", []):
                self.db.execute("INSERT INTO audit(at,order_id,action) VALUES(?,?,?)", row)
            self.db.executemany('INSERT INTO order_trash VALUES(?,?,?,?)', trash)
        return backup

