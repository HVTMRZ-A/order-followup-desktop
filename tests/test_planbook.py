import io
from zipfile import ZipFile
import pytest
from openpyxl import Workbook,load_workbook
from workbench.planbook import read_planbook,export_planbook,edit_cell,displayed
from workbench.storage import Store


def fixture_book(path):
    b=Workbook();s=b.active;s.title='最新';s.append(['订单号','数量','计算']);s.append(['00001',12,'=B2*2'])
    h=b.create_sheet('隐藏配件单');h.sheet_state='hidden';h.append(['不要加入'])
    for name in ['整体配件汇总','家用机订单','包材交期跟进','包材资料未确定','采购回复配件到料','出货计划']:
        b.create_sheet(name).append(['订单号','备注'])
    # 格式残留不应导致读取整百万行。
    s.cell(1048576,16383).number_format='0.00';b.save(path)


def test_visible_sheets_sparse_edit_export(tmp_path):
    source=tmp_path/'source.xlsx';fixture_book(source);original=source.read_bytes()
    payload,blob=read_planbook(source)
    assert len(payload['sheets'])==7
    assert payload['sheets'][0]['rows']==2 and payload['sheets'][0]['cols']==3
    assert all('隐藏' not in s['name'] for s in payload['sheets'])
    sheet=payload['sheets'][0];edit_cell(sheet,'B2',15)
    with pytest.raises(ValueError):edit_cell(sheet,'C2','改公式')
    sheet['formulas_stale']=True;assert displayed(sheet,'C2')=='=B2*2'
    edit_cell(sheet,'A3','00002');target=tmp_path/'export.xlsx';export_planbook(target,payload,blob)
    out=load_workbook(target,read_only=True,data_only=False)
    assert len(out.sheetnames)==7 and '隐藏配件单' not in out.sheetnames
    assert out['最新']['A2'].value=='00001' and out['最新']['B2'].value==15
    assert out['最新']['C2'].value=='=B2*2' and out['最新']['A3'].value=='00002'
    out.close();assert source.read_bytes()==original
    reloaded,_=read_planbook(target);assert len(reloaded['sheets'])==7


def test_store_backup_restore_includes_workbook(tmp_path):
    source=tmp_path/'source.xlsx';fixture_book(source);payload,blob=read_planbook(source)
    store=Store(tmp_path/'db');store.save_planbook(payload,blob)
    backup=tmp_path/'backup.json';store.export_json(backup)
    edit_cell(payload['sheets'][0],'B2',999);store.save_planbook(payload)
    store.restore_json(backup)
    assert store.planbook()['sheets'][0]['cells']['B2']['v']==12
    assert store.planbook_source()==blob
    store.db.close()


def test_ui_seven_sheet_pages(tmp_path,monkeypatch):
    from PySide6.QtWidgets import QApplication,QWidget
    from workbench.plan_ui import PlanBookWidget
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    a=QApplication.instance() or QApplication([])
    source=tmp_path/'source.xlsx';fixture_book(source);payload,blob=read_planbook(source)
    store=Store(tmp_path/'db');store.save_planbook(payload,blob)
    main=QWidget();main.workers=[];w=PlanBookWidget(store,main)
    assert w.tabs.count()==7
    assert [w.tabs.tabText(i) for i in range(7)]==[s['name'] for s in payload['sheets']]
    w.tabs.setCurrentIndex(6);w.add_row();assert store.planbook()['sheets'][6]['rows']==2
    w.close();store.db.close()
