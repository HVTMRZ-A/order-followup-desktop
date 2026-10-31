import base64,csv,io
from pathlib import Path
from datetime import date,timedelta
import pytest
from PySide6.QtCore import Qt,QMimeData,QUrl,QPointF
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication
from openpyxl import Workbook
from workbench.importer import read_any
from workbench.domain import new_order,new_item
from workbench.storage import Store
from workbench.ui import MainWindow,STYLE,OrderDialog
from workbench.order_management import merge_source


@pytest.fixture(scope='module')
def app():
    import os
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    a=QApplication.instance() or QApplication([]);a.setStyleSheet(STYLE);return a


def source_csv(path):
    with path.open('w',encoding='utf-8-sig',newline='') as stream:
        csv.writer(stream).writerows([['订单号','公司型号','数量','料号','产品大类','产品要求','单位','包材','BOM状态','客户特殊说明'],
                                     ['S-001','A',20,'001.002','整机','230V\n需配四个轮子','台','示例包材','新增','原单自定义内容']])
    return read_any(path)[0]


def window(tmp_path,monkeypatch,order):
    monkeypatch.setenv('ORDER_WORKBENCH_DATA',str(tmp_path/'data'));s=Store(tmp_path/'db');s.save_order(order)
    w=MainWindow(s);return w,s


def close(w,s):w.quitting=True;w.close();w.timer.stop();w.tray.hide();s.db.close()


def click_task(w,app,reason):
    item=next(w.todo.item(r,4) for r in range(w.todo.rowCount()) if w.todo.item(r,4).data(Qt.ItemDataRole.UserRole+2) and w.todo.item(r,4).data(Qt.ItemDataRole.UserRole+2)[4]==reason)
    item.setCheckState(Qt.CheckState.Checked);app.processEvents()


def test_extra_import_columns_and_original_are_preserved(tmp_path):
    p=tmp_path/'source.csv';o=source_csv(p);item=o['items'][0]
    assert item['material_code']=='001.002';assert item['requirement']=='230V\n需配四个轮子'
    assert item['source_columns']['客户特殊说明']=='原单自定义内容'
    assert item['packaging_name']=='示例包材' and not item['packaging']
    assert item['bom_status']=='新增' and not item['bom']
    assert base64.b64decode(o['source_original_b64'])==p.read_bytes()
    s=Store(tmp_path/'db');s.save_order(o);s.export_json(tmp_path/'backup.json');s.restore_json(tmp_path/'backup.json')
    assert base64.b64decode(s.orders()[0]['source_original_b64'])==p.read_bytes();s.db.close()


def test_management_navigation_and_full_item_details(app,tmp_path,monkeypatch):
    o=source_csv(tmp_path/'source.csv');w,s=window(tmp_path,monkeypatch,o)
    assert [w.nav.item(i).text() for i in range(w.nav.count())]==['今日待办','订单管理','包材跟进','每日跟进','计划总表','设置与更新']
    w.nav.setCurrentRow(1);assert w.pages.currentWidget() is w.order_management_page
    manager=w.order_management_page;assert manager.table.item(0,2).text()=='001.002'
    assert manager.table.item(0,4).text()=='230V\n需配四个轮子'
    manager.search.setText('001.002');assert manager.table.rowCount()==1
    d=OrderDialog(s,o,w);assert d.order['items'][0]['source_columns']['客户特殊说明']=='原单自定义内容';d.reject()
    w.nav.setCurrentRow(4);assert w.pages.currentWidget() is w.planbook_page;close(w,s)


def test_checkboxes_confirm_only_relevant_states_without_plan_reset(app,tmp_path,monkeypatch):
    o=source_csv(tmp_path/'source.csv');w,s=window(tmp_path,monkeypatch,o)
    o['plan_sync_checked']=True;s.save_plan_join(None,[o]);w.refresh()
    assert not s.orders()[0]['contract']  # 生成勾选框时不能自动保存。
    click_task(w,app,'待确认合同录入');assert s.orders()[0]['contract']
    click_task(w,app,'待确认工程 BOM');assert s.orders()[0]['items'][0]['bom']
    click_task(w,app,'待确认分析');saved=s.orders()[0]
    assert saved['items'][0]['analysis_at']==date.today().isoformat()
    assert saved['plan_sync_checked'] and saved['items'][0]['material_code']=='001.002'
    assert not saved['items'][0]['packaging']
    assert len(s.history(o['id']))>=4;close(w,s)


def test_checkbox_plan_opens_preview_instead_of_silently_joining(app,tmp_path,monkeypatch):
    o=source_csv(tmp_path/'source.csv');w,s=window(tmp_path,monkeypatch,o);calls=[]
    monkeypatch.setattr(w,'confirm_plan_join',lambda orders=None:calls.append(orders))
    click_task(w,app,'待确认加入计划总表')
    assert calls[0][0]['id']==o['id'] and not s.orders()[0]['plan_sync_checked'];assert s.planbook() is None;close(w,s)


def test_daily_checkbox_preserves_notes_and_packaging_checkbox(app,tmp_path,monkeypatch):
    o=source_csv(tmp_path/'source.csv');o['items'][0].update(analyzed=True,analysis_at=(date.today()-timedelta(days=11)).isoformat())
    w,s=window(tmp_path,monkeypatch,o);day=date.today().isoformat();s.save_daily(day,{'分仓数据':{'state':'需要跟进','notes':'待核对料号'}});w.refresh()
    click_task(w,app,'分析满 10 天，包材信息未确认');assert s.orders()[0]['items'][0]['packaging']
    click_task(w,app,'待核对料号');assert s.daily(day)['分仓数据']==dict(state='已处理',notes='待核对料号',updated_at=s.daily(day)['分仓数据']['updated_at']);close(w,s)


def test_dropped_plan_is_routed_to_plan_import_not_order_import(app,tmp_path,monkeypatch):
    o=source_csv(tmp_path/'source.csv');w,s=window(tmp_path,monkeypatch,o)
    p=tmp_path/'total.xlsx';b=Workbook();b.active.title='最新';b.create_sheet('出货计划');b.save(p)
    received=[];monkeypatch.setattr(w.planbook_page,'import_path',lambda p:received.append(p))
    mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(p))]);event=QDropEvent(QPointF(10,10),Qt.DropAction.CopyAction,mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
    w.planbook_page.dropEvent(event);assert [Path(x) for x in received]==[p]
    imports=[];monkeypatch.setattr(w,'confirm_import',lambda orders,source:imports.extend(orders))
    other=tmp_path/'other.csv';source_csv(other)
    # 使用空已有订单列表，单独核对订单文件的分流。
    monkeypatch.setattr(s,'orders',lambda:[]);w.import_files([str(other)]);assert imports[0]['items'][0]['material_code']=='001.002';close(w,s)


def test_supplement_only_fills_blanks_keeps_manual_confirmations(tmp_path):
    incoming=source_csv(tmp_path/'source.csv');old=new_order();old['number']='S-001';old['items']=[new_item('A','20')]
    old['contract']=True;old['items'][0].update(bom=True,requirement='用户已修订要求')
    merged,changes,conflicts=merge_source(old,incoming)
    assert merged['contract'] and merged['items'][0]['bom']
    assert merged['items'][0]['material_code']=='001.002' and merged['items'][0]['requirement']=='用户已修订要求'
    assert conflicts and base64.b64decode(merged['source_original_b64'])==(tmp_path/'source.csv').read_bytes()
