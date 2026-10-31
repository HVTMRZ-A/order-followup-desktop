import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QDate, QMimeData, QUrl
from workbench.ui import MainWindow, OrderDialog, STYLE, ORDERS_HEADERS
from workbench.production import (HOME_COLUMNS, PACKAGING_COLUMNS, PARTS_COLUMNS, PLAN_COLUMNS)
from workbench.storage import Store
from workbench.domain import new_order, new_item


@pytest.fixture(scope="module")
def app():
    a=QApplication.instance() or QApplication([]);a.setStyleSheet(STYLE);return a


def test_save_order_daily_and_model_override(app,tmp_path,monkeypatch):
    monkeypatch.setenv("ORDER_WORKBENCH_DATA",str(tmp_path))
    s=Store(tmp_path/"db");o=new_order();o["number"]="UI-001";o["items"]=[new_item("A","10"),new_item("B","20")];s.save_order(o)
    w=MainWindow(s);dialog=OrderDialog(s,o,w)
    dialog.bulk("bom");dialog.bulk("analyzed");dialog.order["items"][1]["bom"]=False;dialog.save()
    saved=s.orders()[0];assert saved["items"][0]["bom"] and not saved["items"][1]["bom"]
    assert all(i["analyzed"] for i in saved["items"])
    old=w.current_daily_day
    state,notes=w.daily_widgets["分仓数据"];notes.setText("UI-001 异常待跟进");state.setCurrentText("需要跟进")
    assert s.daily(old)["分仓数据"]["state"]=="需要跟进"
    w.daily_date.setDate(QDate(2026,1,1));assert w.current_daily_day=="2026-01-01"
    assert s.daily(old)["分仓数据"]["notes"]=="UI-001 异常待跟进"
    w.refresh();assert any(w.todo.item(r,1).text()=="每日记录" for r in range(w.todo.rowCount()))
    w.quitting=True;w.close();w.timer.stop();w.tray.hide();s.db.close()


def test_todo_groups_collapse_and_expand(app,tmp_path,monkeypatch):
    monkeypatch.setenv("ORDER_WORKBENCH_DATA",str(tmp_path))
    s=Store(tmp_path/"db2");o=new_order();o["number"]="UI-002"
    o["items"]=[new_item("A","10"),new_item("B","20")];o["received_at"]="2026-10-01T09:00:00"
    s.save_order(o);w=MainWindow(s);w.refresh()
    pairs=[pair for pair in w.todo_groups.values() if pair[1]]
    assert pairs,"同一订单的多条待办应合并成一组"
    header,children=pairs[0]
    assert all(not w.todo.isRowHidden(row) for row in children)
    assert "－" in w.todo.item(header,1).text()
    w.toggle_todo_group(header,0)
    assert all(w.todo.isRowHidden(row) for row in children)
    assert "＋" in w.todo.item(header,1).text()
    w.toggle_todo_group(header,0)
    assert all(not w.todo.isRowHidden(row) for row in children)
    w.quitting=True;w.close();w.timer.stop();w.tray.hide();s.db.close()


def test_orders_table_matches_plan_sheet(app,tmp_path,monkeypatch):
    monkeypatch.setenv("ORDER_WORKBENCH_DATA",str(tmp_path))
    s=Store(tmp_path/"db3");o=new_order();o["number"]="UI-003";o["customer_no"]="D299"
    o["plan_serial"]="X2601352";o["items"]=[new_item("LE2000-4B","580")]
    o["items"][0]["requirement"]="壁挂款，230V/50Hz，输出功率2kW"
    s.save_order(o);w=MainWindow(s);w.refresh()
    assert w.orders_table.columnCount()==len(PLAN_COLUMNS)+2
    assert [w.orders_table.horizontalHeaderItem(i).text() for i in range(1,len(PLAN_COLUMNS)+1)]==PLAN_COLUMNS
    first=1+PLAN_COLUMNS.index("订单号")
    assert w.orders_table.item(0,first).text()=="UI-003"
    assert w.orders_table.item(0,1).text()=="X2601352"
    assert w.order_tabs.count()==4
    assert [w.order_tabs.tabText(i) for i in range(4)]==["整机订单","整体配件汇总","家用机订单","包材资料未确定"]
    assert w.parts_table.columnCount()==len(PARTS_COLUMNS)
    assert w.home_table.columnCount()==len(HOME_COLUMNS)
    assert w.pack_table.columnCount()==len(PACKAGING_COLUMNS)
    assert w.parts_table.rowCount()==1 and w.pack_table.rowCount()==1
    w.quitting=True;w.close();w.timer.stop();w.tray.hide();s.db.close()


def test_drop_only_accepts_order_files(app,tmp_path,monkeypatch):
    monkeypatch.setenv("ORDER_WORKBENCH_DATA",str(tmp_path))
    s=Store(tmp_path/"db4");w=MainWindow(s)
    mime=QMimeData()
    mime.setUrls([QUrl.fromLocalFile(r"C:\tmp\26LTJX2043.xlsx"),
                  QUrl.fromLocalFile(r"C:\tmp\数据.CSV"),
                  QUrl.fromLocalFile(r"C:\tmp\说明.txt")])
    paths=w.drop_paths(mime)
    assert [os.path.basename(p) for p in paths]==["26LTJX2043.xlsx","数据.CSV"]
    empty=QMimeData();assert w.drop_paths(empty)==[]
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QDragEnterEvent
    w.show();app.processEvents()
    enter=QDragEnterEvent(QPoint(10,10),Qt.DropAction.CopyAction,mime,Qt.MouseButton.LeftButton,
                          Qt.KeyboardModifier.NoModifier)
    w.dragEnterEvent(enter)
    assert w.drop_overlay.isVisible()
    w.dragLeaveEvent(None)
    assert not w.drop_overlay.isVisible()
    w.quitting=True;w.close();w.timer.stop();w.tray.hide();s.db.close()
