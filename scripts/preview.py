"""生成示例界面截图；全部使用独立测试数据。"""
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ["ORDER_WORKBENCH_DATA"]=str(ROOT/"outputs"/"preview-data")
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from PySide6.QtCore import QTimer
from workbench.domain import new_order,new_item,confirm_all,uid
from workbench.storage import Store
from workbench.ui import MainWindow,STYLE,OrderDialog

a=QApplication([])
for font in ["msyh.ttc","msyhbd.ttc"]:QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR","C:/Windows"))/"Fonts"/font))
a.setStyle("Fusion");a.setStyleSheet(STYLE);s=Store()
if not s.orders():
    o=new_order();o.update(number="演示-SO-001",customer="示例客户 · 非真实订单",owner="张三",contract_owner="张三",sales_owner="李四",received_at="2026-10-01T08:00:00",contract_no="演示-HT-001",sales_no="演示-XS-001")
    o["items"]=[new_item("型号 A","500"),new_item("型号 B","200")];confirm_all(o,"bom",True);confirm_all(o,"analyzed",True,"2026-10-01")
    o["materials"]=[dict(id=uid(),item_id=o["items"][0]["id"],name="外箱",usage="0.1",unit="个",arrived="20",due_date="2026-10-29",remind_date="2026-10-28",request_no="演示-QG-001")];s.save_order(o)
    s.save_daily("2026-10-30",{"分仓数据":{"state":"需要跟进","notes":"演示-SO-001：待核对物料数量"}})
w=MainWindow(s);w.show();a.processEvents();w.grab().save(str(ROOT/"outputs"/"preview-dashboard.png"))
w.nav.setCurrentRow(1);a.processEvents();w.grab().save(str(ROOT/"outputs"/"preview-orders.png"))
d=OrderDialog(s,s.orders()[0],w);d.show();a.processEvents();d.grab().save(str(ROOT/"outputs"/"preview-order-detail.png"));d.reject()
w.quitting=True;w.close();w.tray.hide();s.db.close()
print("Preview screenshots saved")
