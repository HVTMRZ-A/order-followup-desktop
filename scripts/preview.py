"""生成界面截图；全部使用独立测试数据，不触碰真实库。"""
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["ORDER_WORKBENCH_DATA"] = str(ROOT / "outputs" / "preview-data")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication, QTabWidget  # noqa: E402

from workbench.domain import confirm_all, new_item, new_order, uid  # noqa: E402
from workbench.storage import Store  # noqa: E402
from workbench.ui import STYLE, ItemDialog, MainWindow, MaterialDialog, OrderDialog  # noqa: E402

OUT = ROOT / "outputs"
OUT.mkdir(exist_ok=True)
FONTS = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"

app = QApplication([])
for name in ("msyh.ttc", "msyhbd.ttc"):
    QFontDatabase.addApplicationFont(str(FONTS / name))
app.setStyle("Fusion")
app.setStyleSheet(STYLE)


def seed(store):
    """造几条不同状态的演示订单，覆盖紧急 / 高 / 正常 / 完成。"""
    if store.orders():
        return
    today = date.today()
    now = datetime.now()

    a = new_order()
    a.update(number="演示-SO-001", customer="台州华鼎贸易有限公司", owner="张三", contract_owner="张三",
             sales_owner="李四", received_at=(now - timedelta(days=3)).isoformat(timespec="seconds"),
             contract_no="演示-HT-001", sales_no="演示-XS-001", contract=True,
             notes="客户要求分两批出货，第二批等包材到齐后确认。")
    a["items"] = [new_item("LF3000-A", "500"), new_item("LF6200-A", "200")]
    confirm_all(a, "bom", True)
    confirm_all(a, "analyzed", True, (today - timedelta(days=12)).isoformat())
    a["materials"] = [
        dict(id=uid(), item_id=a["items"][0]["id"], name="外箱 5 层瓦楞", usage="0.1", unit="个", arrived="20",
             due_date=(today - timedelta(days=2)).isoformat(), remind_date=(today - timedelta(days=3)).isoformat(),
             request_no="演示-QG-001", buyer="王五"),
        dict(id=uid(), item_id=a["items"][1]["id"], name="说明书（英文）", usage="1", unit="份", arrived="200",
             due_date=(today + timedelta(days=4)).isoformat(), request_no="演示-QG-002", buyer="王五"),
    ]
    store.save_order(a)

    b = new_order()
    b.update(number="演示-SO-002", customer="宁波海翔电子科技有限公司", owner="李四",
             received_at=(now - timedelta(days=4)).isoformat(timespec="seconds"), contract_no="演示-HT-002")
    b["items"] = [new_item("LF8600-A", "120"), new_item("LF11000-A", "60")]
    b["items"][0]["bom"] = True
    b["items"][1]["bom"] = True
    b["items"][0]["analyzed"] = True
    b["items"][0]["analysis_at"] = (today - timedelta(days=3)).isoformat()
    store.save_order(b)

    c = new_order()
    c.update(number="演示-SO-003", customer="杭州昱能科技股份有限公司", owner="赵敏", contract_owner="赵敏",
             received_at=(now - timedelta(days=9)).isoformat(timespec="seconds"), contract=True)
    c["items"] = [new_item("SHI-6205", "300")]
    confirm_all(c, "bom", True)
    confirm_all(c, "analyzed", True, (today - timedelta(days=8)).isoformat())
    confirm_all(c, "packaging", True)
    confirm_all(c, "completed", True)
    store.save_order(c)

    d = new_order()
    d.update(number="演示-SO-004", customer="苏州锦浪新能源有限公司", owner="孙倩",
             received_at=(now - timedelta(days=1)).isoformat(timespec="seconds"), contract=True)
    d["items"] = [new_item("LF4000-6A", "80")]
    store.save_order(d)

    store.save_daily(today.isoformat(), {"分仓数据": {"state": "需要跟进", "notes": "演示-SO-001：待核对散件数量"},
                                          "成品入库数据": {"state": "无需跟进", "notes": ""}})
    store.save_daily((today - timedelta(days=1)).isoformat(),
                     {"销售出库数据": {"state": "需要跟进", "notes": "演示-SO-003 出库单待回签"}})


store = Store()
seed(store)
window = MainWindow(store)
window.show()
app.processEvents()

for index, name in enumerate(["dashboard", "orders", "materials", "daily", "settings"]):
    window.nav.setCurrentRow(index)
    app.processEvents()
    window.grab().save(str(OUT / f"ui-{name}.png"))

order = next(o for o in store.orders() if o["number"] == "演示-SO-001")
dialog = OrderDialog(store, order, window)
dialog.show()
tabs = dialog.findChild(QTabWidget)
for index, name in enumerate(["basic", "items", "materials", "history"]):
    tabs.setCurrentIndex(index)
    app.processEvents()
    dialog.grab().save(str(OUT / f"ui-order-{name}.png"))
dialog.reject()

item_dialog = ItemDialog(order["items"][0], window)
item_dialog.show()
app.processEvents()
item_dialog.grab().save(str(OUT / "ui-item-dialog.png"))
item_dialog.reject()

material_dialog = MaterialDialog(order, order["materials"][0], window)
material_dialog.show()
app.processEvents()
material_dialog.grab().save(str(OUT / "ui-material-dialog.png"))
material_dialog.reject()

window.quitting = True
window.timer.stop()
window.close()
window.tray.hide()
store.db.close()
print("screenshots ->", OUT)
