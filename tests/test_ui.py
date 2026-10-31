import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QDate
from workbench.ui import MainWindow, OrderDialog, STYLE
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
