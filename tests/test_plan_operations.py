import copy,os
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit,QMessageBox
from openpyxl import load_workbook
from workbench.production import PLAN_COLUMNS
from workbench.planbook import export_planbook
from test_inline_edit import ui
from test_cell_format import select


def test_clear_range_is_atomic_undoable_and_keeps_formula(ui):
    app,w,s,o=ui;w.nav.setCurrentRow(4);p=w.planbook_page
    assert p.commit_cell(0,1,PLAN_COLUMNS.index('备注'),'备注一')
    assert p.commit_cell(0,2,PLAN_COLUMNS.index('备注'),'备注二')
    app.processEvents();before=len(w.edit_history.undo_stack);t=p.tables[0];select(t,1,PLAN_COLUMNS.index('备注'),2,PLAN_COLUMNS.index('备注'))
    t.setFocus();QTest.keyClick(t,Qt.Key.Key_Delete);app.processEvents()
    assert len(w.edit_history.undo_stack)==before+1
    assert s.planbook()['sheets'][0]['cells']['AE2']['v']=='' and s.planbook()['sheets'][0]['cells']['AE3']['v']==''
    assert 'f' in s.planbook()['sheets'][0]['cells']['AM2']
    w.replay_edit();app.processEvents();assert s.planbook()['sheets'][0]['cells']['AE2']['v']=='备注一'
    select(p.tables[0],1,0,1,11);snapshot=s.planbook();assert not p.clear_selected()
    assert s.planbook()==snapshot and s.orders()[0]['items'][0]['quantity']=='10'


def test_remove_only_current_plan_links_preserves_master_and_export(ui,tmp_path,monkeypatch):
    app,w,s,o=ui;w.nav.setCurrentRow(4);p=w.planbook_page;data=s.planbook()
    extra=dict(order_id=o['id'],item_id=o['items'][0]['id'],sheet='出货计划',row=3);data['order_links'].append(extra);s.save_planbook(data);p.reload()
    select(p.tables[0],1,7);count=p.tables[0].rowCount()
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.StandardButton.Yes)
    assert p.remove_selected_records();app.processEvents();after=s.planbook()
    assert p.tables[0].rowCount()==count and after['sheets'][0]['cells']['H2']['v']==''
    assert after['sheets'][0]['cells']['H3']['v']=='B' and 'f' in after['sheets'][0]['cells']['AM2']
    assert extra in after['order_links'] and not any(l['sheet']=='最新' and l['row']==2 for l in after['order_links'])
    assert len(s.orders()[0]['items'])==2 and s.orders()[0]['items'][0]['quantity']=='10' and s.orders()[0]['materials'][0]['name']=='box'
    assert list((s.path.parent/'backups').glob('*.sqlite3'))
    target=tmp_path/'removed.xlsx';export_planbook(target,after,s.planbook_source());book=load_workbook(target)
    assert book.active['H2'].value is None and book.active['H3'].value=='B' and book.active['AM2'].value=='=L2*2';book.close()
    w.replay_edit();app.processEvents();assert s.planbook()['order_links']==data['order_links'] and s.planbook()['sheets'][0]['cells']['H2']['v']=='A'
    w.replay_edit(True);app.processEvents();assert s.planbook()['sheets'][0]['cells']['H2']['v']==''


def test_partial_merged_removal_cancel_and_header_protection(ui,monkeypatch):
    app,w,s,o=ui;w.nav.setCurrentRow(4);p=w.planbook_page;p.tabs.setCurrentIndex(1);select(p.tables[1],2,1)
    before=s.planbook();monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.StandardButton.No)
    assert not p.remove_selected_records() and s.planbook()==before
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.StandardButton.Yes)
    assert p.remove_selected_records();sheet=s.planbook()['sheets'][1]
    assert sheet['cells']['A3']['v']=='HISTORY' and sheet['cells']['B4']['v']=='Y' and sheet['cells']['B3']['v']==''
    select(p.tables[1],0,0);before=s.planbook();assert not p.remove_selected_records() and s.planbook()==before


def test_save_ctrl_s_commits_open_editor_and_pending_width(ui):
    app,w,s,o=ui;w.nav.setCurrentRow(4);p=w.planbook_page;t=p.tables[0];select(t,1,PLAN_COLUMNS.index('备注'))
    QTest.keyClick(t,Qt.Key.Key_F2);app.processEvents();editor=next(e for e in t.findChildren(QLineEdit) if e.isVisible());editor.setText('尚未回车也应保存')
    t.setColumnWidth(1,237);QTest.keyClick(editor,Qt.Key.Key_S,Qt.KeyboardModifier.ControlModifier);app.processEvents()
    assert s.planbook()['sheets'][0]['cells']['AE2']['v']=='尚未回车也应保存'
    assert s.planbook()['sheets'][0]['dimension_edits']['columns']['2']==237
    assert s.get('planbook_saved_at') and '最近保存' in p.saved_info.text()
    assert p.export_button.text()=='导出' and not any(b.text()=='另存为 Excel' for b in p.findChildren(type(p.export_button)))


def test_invalid_input_save_fails_and_does_not_claim_success(ui):
    app,w,s,o=ui;w.nav.setCurrentRow(4);p=w.planbook_page;t=p.tables[0];select(t,1,PLAN_COLUMNS.index('订单数量'))
    QTest.keyClick(t,Qt.Key.Key_F2);app.processEvents();editor=next(e for e in t.findChildren(QLineEdit) if e.isVisible());editor.setText('0')
    assert not p.save_current();assert s.orders()[0]['items'][0]['quantity']=='10' and '未保存' in p.status.text()
