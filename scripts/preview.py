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
from workbench.importer import read_any  # noqa: E402
from workbench.storage import Store  # noqa: E402
from workbench.ui import (STYLE, ImportPreviewDialog, ItemDialog, MainWindow,  # noqa: E402
                          MaterialDialog, OrderDialog)

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
    a.update(number="演示-SO-001", customer="台州华鼎贸易有限公司", customer_no="D010", owner="张三",
             contract_owner="张三", sales_owner="李四", plan_serial="X2601352", transport="1*40HQ",
             attribute="新增", received_at=(now - timedelta(days=3)).isoformat(timespec="seconds"),
             contract_no="演示-HT-001", sales_no="演示-XS-001", contract=True,
             notes="客户要求分两批出货，第二批等包材到齐后确认。")
    a["items"] = [new_item("LF3000-A", "500"), new_item("LF6200-A", "200")]
    a["items"][0].update(category="储能逆变器-外", material_code="3.21.01.02.03.0014",
                         requirement="LF3000-A_220V/230V/240V_50Hz/60Hz_AC输出3000W_PV 3000W*1_无并机线_绿田英文_覆膜彩包_非认证")
    a["items"][1].update(category="储能逆变器-外", material_code="3.21.01.02.07.0008",
                         requirement="LF6200-A_220V/230V/240V_50Hz/60Hz_AC输出6200W_PV 8500W*1_带并机线_绿田英文_覆膜彩包_非认证")
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

# 导入预览：优先用桌面上的真实生产单，没有就现场造一份等价结构
sample = Path.home() / "Desktop" / "计划工作台" / "26LTJX2043 生产单 LE2000-4B.xlsx"
if not sample.exists():
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.append(["绿田机械股份有限公司     V1.3"])
    sheet.append([])
    sheet.append(["2026年10月份生产作业计划单"])
    sheet.append(["整机生产单"])
    sheet.append(["", "合同编号：", "26LTJX2043", "", "", "", "", "订单属性：", "新增"])
    sheet.append(["", "客户编号：", "D299", "", "", "", "", "数量：", 580])
    sheet.append(["计划完成日期:", "", 46356, "", "", "", "", "运输方式：", "1*40HQ"])
    sheet.append(["序号", "产品大类", "客户型号", "公司型号", "数量", "单位", "产品要求", "包材", "BOM状态", "物料代码"])
    sheet.append([1, "太阳能发电机", "", "LE2000-4B", 580, "台",
                  "壁挂款，230V/50Hz，输出功率2kW，电池容量4019Wh，英插电源线", "绿田", "新增", "3.21.00.01.02.10011"])
    sheet.append(["注意事项：", "", "1.商标和纸箱按照尼日利亚办事处指定的设计"])
    sheet.append(["", "复核：", "", "", "", "", "", "经办人：", "戴爽"])
    sheet.append(["", "批准：", "", "", "", "", "", "下单日期：", 46323])
    sample = ROOT / "outputs" / "preview-data" / "sample-production.xlsx"
    book.save(sample)

import_orders = read_any(sample)
import_dialog = ImportPreviewDialog(import_orders, store, window, sample.name)
import_dialog.show()
app.processEvents()
import_dialog.grab().save(str(OUT / "ui-import-detail.png"))
tabs = import_dialog.findChild(QTabWidget)
tabs.setCurrentIndex(1)
app.processEvents()
import_dialog.grab().save(str(OUT / "ui-import-plan.png"))
import_dialog.reject()

# 待办分组折叠态 / 订单总表右侧列 / 拖拽遮罩
window.nav.setCurrentRow(0)
app.processEvents()
pairs = [pair for pair in window.todo_groups.values() if pair[1]]
if pairs:
    window.toggle_todo_group(pairs[0][0], 0)
    app.processEvents()
    window.grab().save(str(OUT / "ui-todo-collapsed.png"))
    window.toggle_todo_group(pairs[0][0], 0)
window.nav.setCurrentRow(1)
app.processEvents()
bar = window.orders_table.horizontalScrollBar()
bar.setValue(bar.maximum())
app.processEvents()
window.grab().save(str(OUT / "ui-orders-right.png"))
window.show_drop_overlay(True)
app.processEvents()
window.grab().save(str(OUT / "ui-drop-overlay.png"))
window.show_drop_overlay(False)

window.quitting = True
window.timer.stop()
window.close()
window.tray.hide()
store.db.close()
print("screenshots ->", OUT)
