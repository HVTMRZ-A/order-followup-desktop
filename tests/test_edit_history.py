import copy
from datetime import date
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit
from workbench.domain import new_order, new_item, demand
from workbench.storage import Store
from workbench.edit_history import EditHistory
from workbench.production import PLAN_COLUMNS
from test_inline_edit import ui, edit_keyboard


def test_plan_undo_redo_restores_order_quantity_and_demand(ui):
    app,w,s,o=ui;w.nav.setCurrentRow(4);p=w.planbook_page
    assert p.commit_cell(0,1,PLAN_COLUMNS.index('订单数量'),'25')
    assert len(w.edit_history.undo_stack)==1
    w.replay_edit();app.processEvents()
    assert s.orders()[0]['items'][0]['quantity']=='10'
    assert demand(s.orders()[0],s.orders()[0]['materials'][0])==20
    assert s.planbook()['sheets'][0]['cells']['L2']['v']=='10'
    w.replay_edit(True);app.processEvents()
    assert s.orders()[0]['items'][0]['quantity']=='25'
    assert s.planbook()['sheets'][0]['cells']['L2']['v']==25


def test_keyboard_shortcuts_and_editor_native_undo(ui):
    app,w,s,o=ui;w.nav.setCurrentRow(1);t=w.order_management_page.table
    edit_keyboard(app,t,0,3,'12');t.setFocus();app.processEvents()
    QTest.keyClick(t,Qt.Key.Key_Z,Qt.KeyboardModifier.ControlModifier);app.processEvents()
    assert s.orders()[0]['items'][0]['quantity']=='10'
    QTest.keyClick(t,Qt.Key.Key_Y,Qt.KeyboardModifier.ControlModifier);app.processEvents()
    assert s.orders()[0]['items'][0]['quantity']=='12'
    t.setCurrentCell(0,4);QTest.keyClick(t,Qt.Key.Key_F2);app.processEvents()
    editor=next(e for e in t.findChildren(QLineEdit) if e.isVisible())
    original=editor.text();QTest.keyClicks(editor,'ABC');QTest.keyClick(editor,Qt.Key.Key_Z,Qt.KeyboardModifier.ControlModifier);app.processEvents()
    assert editor.text()==original and s.orders()[0]['items'][0]['quantity']=='12'
    QTest.keyClick(editor,Qt.Key.Key_Escape)


def test_material_undo_and_branch_clears_redo(ui):
    app,w,s,o=ui;w.nav.setCurrentRow(2)
    edit_keyboard(app,w.material_table,0,10,'4')
    w.replay_edit();app.processEvents()
    assert s.orders()[0]['materials'][0]['usage']=='2'
    assert w.redo_action.isEnabled()
    edit_keyboard(app,w.material_table,0,7,'2026-12-05')
    assert not w.redo_action.isEnabled()
    w.replay_edit();app.processEvents()
    assert s.orders()[0]['materials'][0]['due_date']=='2026-12-01'


def test_analysis_undo_includes_daily_followup(ui):
    app,w,s,o=ui;p=w.planbook_page;day=date.today().isoformat();before=s.daily(day)
    assert p.commit_cell(0,1,PLAN_COLUMNS.index('分析时间'),'2026-11-03')
    assert s.orders()[0]['items'][0]['analyzed']
    assert o['id'] in s.daily(day)['分仓数据']['order_ids']
    w.replay_edit();app.processEvents()
    assert not s.orders()[0]['items'][0]['analyzed'] and s.daily(day)==before
    w.replay_edit(True);app.processEvents()
    assert s.orders()[0]['items'][0]['analyzed'] and o['id'] in s.daily(day)['分仓数据']['order_ids']


def test_conflict_refuses_without_overwriting_and_preserves_unrelated_changes(tmp_path):
    s=Store(tmp_path/'db');o=new_order();o.update(number='A',items=[new_item('X','1')]);s.save_order(o);h=EditHistory(s)
    before=h.capture([o['id']]);o['items'][0]['quantity']='5';s.save_order(o);h.record('数量',before)
    current=s.orders()[0];current['customer']='新客户';s.save_order(current)
    h.undo();assert s.orders()[0]['customer']=='新客户' and s.orders()[0]['items'][0]['quantity']=='1'
    h.redo();current=s.orders()[0];current['items'][0]['quantity']='8';s.save_order(current)
    with pytest.raises(ValueError,match='新的修改'):h.undo()
    assert s.orders()[0]['items'][0]['quantity']=='8' and len(h.undo_stack)==1
    s.db.close()


def test_reimport_prevents_old_plan_undo_and_noop_not_recorded(ui):
    app,w,s,o=ui;h=w.edit_history
    before=h.capture([o['id']]);h.record('无变化',before);assert not h.undo_stack
    assert w.planbook_page.commit_cell(0,1,PLAN_COLUMNS.index('订单数量'),'30')
    s.save_planbook(s.planbook(),s.planbook_source())
    with pytest.raises(ValueError,match='重新导入'):h.undo()
    assert s.orders()[0]['items'][0]['quantity']=='30'


def test_daily_undo_and_added_plan_row(ui):
    app,w,s,o=ui;w.nav.setCurrentRow(3);day=w.current_daily_day
    w.daily_widgets['分仓数据'][0].setCurrentText('需要跟进');app.processEvents()
    w.pages.setFocus();w.replay_edit();app.processEvents()
    assert s.daily(day).get('分仓数据',{}).get('state')!='需要跟进'
    w.nav.setCurrentRow(4);p=w.planbook_page;rows=p.tables[0].rowCount();p.add_row()
    w.pages.setFocus();w.replay_edit();app.processEvents();assert p.tables[0].rowCount()==rows


def test_undo_uses_stable_model_ids_after_reordering_and_atomic_unique_conflict(tmp_path):
    s=Store(tmp_path/'db');o=new_order();o.update(number='A',items=[new_item('X','1'),new_item('Y','2')]);s.save_order(o);h=EditHistory(s)
    before=h.capture([o['id']]);o['items'][0]['quantity']='5';s.save_order(o);h.record('数量',before)
    current=s.orders()[0];current['items'].reverse();s.save_order(current);h.undo()
    saved=s.orders()[0];assert [(i['model'],i['quantity']) for i in saved['items']]==[('Y','2'),('X','1')]
    before=h.capture([o['id']]);saved['number']='B';s.save_order(saved);h.record('改号',before)
    other=new_order();other.update(number='A',items=[new_item('Z','1')]);s.save_order(other)
    with pytest.raises(Exception,match='UNIQUE'):h.undo()
    assert next(x for x in s.orders() if x['id']==o['id'])['number']=='B' and len(h.undo_stack)==1
    s.db.close()
