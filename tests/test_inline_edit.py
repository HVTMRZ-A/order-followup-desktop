import os
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QLineEdit
from PySide6.QtTest import QTest
from openpyxl import Workbook
from workbench.domain import new_order,new_item,demand
from workbench.production import PLAN_COLUMNS,plan_rows
from workbench.planbook import read_planbook
from workbench.storage import Store
from workbench.ui import MainWindow,STYLE


@pytest.fixture
def ui(tmp_path,monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen');monkeypatch.setenv('ORDER_WORKBENCH_DATA',str(tmp_path/'data'))
    app=QApplication.instance() or QApplication([]);app.setStyleSheet(STYLE)
    store=Store(tmp_path/'db');order=new_order();order['number']='INLINE-1';order['items']=[new_item('A','10'),new_item('B','20')]
    order['items'][0].update(material_code='001.002',requirement='230V')
    order['materials']=[dict(id='m1',item_id=order['items'][0]['id'],name='box',usage='2',arrived='1',due_date='2026-12-01')]
    store.save_order(order)
    book=Workbook();sheet=book.active;sheet.title='最新';sheet.append(PLAN_COLUMNS+['计算'])
    for values in plan_rows(order)[0]:sheet.append([values[n] for n in PLAN_COLUMNS])
    sheet.cell(2,len(PLAN_COLUMNS)+1,'=L2*2')
    other=book.create_sheet('出货计划');other['A1']='出货标题';other.merge_cells('A1:D1');other.append(['订单号','型号','备注'])
    other.append(['HISTORY','X','旧备注']);other.append([None,'Y','']);other.merge_cells('A3:A4')
    path=tmp_path/'book.xlsx';book.save(path);p,blob=read_planbook(path)
    p['order_links']=[dict(order_id=order['id'],item_id=item['id'],sheet='最新',row=n+2) for n,item in enumerate(order['items'])]
    store.save_planbook(p,blob);window=MainWindow(store);window.show();app.processEvents()
    yield app,window,store,order
    window.quitting=True;window.close();window.timer.stop();window.tray.hide();store.db.close()


def edit_keyboard(app,table,row,col,text,key=Qt.Key.Key_Return):
    table.scrollToItem(table.item(row,col))
    rect=table.visualRect(table.model().index(row,col))
    QTest.mouseClick(table.viewport(),Qt.MouseButton.LeftButton,pos=rect.center());app.processEvents()
    assert not any(e.isVisible() for e in table.findChildren(QLineEdit)),'单击只应选中单元格'
    QTest.keyClick(table,Qt.Key.Key_F2);app.processEvents()
    editors=[e for e in table.findChildren(QLineEdit) if e.isVisible()]
    assert editors,'F2 应进入编辑状态'
    editor=editors[-1];QTest.keyClick(editor,Qt.Key.Key_A,Qt.KeyboardModifier.ControlModifier);QTest.keyClicks(editor,text);QTest.keyClick(editor,key);QTest.qWait(10);app.processEvents()


def test_plan_selection_then_edit_saves_and_updates_shared_order(ui):
    app,w,s,o=ui;w.nav.setCurrentRow(4);t=w.planbook_page.tables[0]
    edit_keyboard(app,t,1,PLAN_COLUMNS.index('订单数量'),'25')
    saved=s.orders()[0];assert saved['items'][0]['quantity']=='25'
    assert demand(saved,saved['materials'][0])==50
    assert s.planbook()['sheets'][0]['cells']['L2']['v']==25
    assert not saved['plan_sync_checked']


def test_escape_cancels_without_changing_workbook(ui):
    app,w,s,o=ui;w.nav.setCurrentRow(4);t=w.planbook_page.tables[0]
    before=s.planbook();edit_keyboard(app,t,1,PLAN_COLUMNS.index('订单数量'),'999',Qt.Key.Key_Escape)
    assert s.planbook()==before and s.orders()[0]['items'][0]['quantity']=='10'


def test_tab_commits_and_selects_next_cell_without_editing(ui):
    app,w,s,o=ui;w.nav.setCurrentRow(4);t=w.planbook_page.tables[0]
    edit_keyboard(app,t,1,PLAN_COLUMNS.index('物料编码'),'000123',Qt.Key.Key_Tab)
    editors=[e for e in t.findChildren(QLineEdit) if e.isVisible()]
    assert not editors and t.currentColumn()==PLAN_COLUMNS.index('类别')
    QTest.keyClick(t,Qt.Key.Key_C);app.processEvents()
    editor=next(e for e in t.findChildren(QLineEdit) if e.isVisible());QTest.keyClicks(editor,'ategory');QTest.keyClick(editor,Qt.Key.Key_Return);QTest.qWait(10);app.processEvents()
    saved=s.orders()[0]['items'][0]
    assert saved['material_code']=='000123' and saved['category']=='category'


def test_invalid_plan_quantity_date_and_duplicate_order_roll_back(ui):
    app,w,s,o=ui;p=w.planbook_page;before=s.planbook()
    assert not p.commit_cell(0,1,PLAN_COLUMNS.index('订单数量'),'0')
    assert not p.commit_cell(0,1,PLAN_COLUMNS.index('生产单交期'),'tomorrow')
    other=new_order();other['number']='EXISTS';other['items']=[new_item('C','1')];s.save_order(other)
    assert not p.commit_cell(0,1,PLAN_COLUMNS.index('订单号'),'EXISTS')
    assert s.planbook()==before
    saved=next(x for x in s.orders() if x['id']==o['id']);assert saved['number']=='INLINE-1' and saved['items'][0]['quantity']=='10'


def test_formula_readonly_and_merged_cell_edit_uses_anchor(ui):
    app,w,s,o=ui;p=w.planbook_page;t=p.tables[0]
    assert not t.item(1,len(PLAN_COLUMNS)).flags() & Qt.ItemFlag.ItemIsEditable
    assert not p.commit_cell(0,1,len(PLAN_COLUMNS),'bad')
    assert p.commit_cell(1,3,0,'HISTORY-NEW')
    assert s.planbook()['sheets'][1]['cells']['A3']['v']=='HISTORY-NEW'
    assert 'A4' not in s.planbook()['sheets'][1]['edits']


def test_order_management_direct_edit_and_invalid_model(ui):
    app,w,s,o=ui;w.nav.setCurrentRow(1);m=w.order_management_page
    edit_keyboard(app,m.table,0,3,'12')
    assert s.orders()[0]['items'][0]['quantity']=='12'
    assert w.material_table.item(0,3).text()=='24'
    m.table.item(0,1).setText('B');app.processEvents()
    assert s.orders()[0]['items'][0]['model']=='A' and m.table.item(0,1).text()=='A'
    assert not m.table.item(0,17).flags() & Qt.ItemFlag.ItemIsEditable


def test_material_usage_arrival_and_dates_edit_with_validation(ui):
    app,w,s,o=ui;w.nav.setCurrentRow(2);t=w.material_table
    edit_keyboard(app,t,0,10,'3')
    assert s.orders()[0]['materials'][0]['usage']=='3'
    assert t.item(0,3).text()=='30' and t.item(0,6).text()=='29'
    t.item(0,5).setText('5');app.processEvents();assert s.orders()[0]['materials'][0]['arrived']=='5'
    t.item(0,7).setText('2026/12/03');app.processEvents();assert s.orders()[0]['materials'][0]['due_date']=='2026-12-03'
    t.item(0,10).setText('-1');app.processEvents();assert s.orders()[0]['materials'][0]['usage']=='3'
    assert not t.item(0,3).flags() & Qt.ItemFlag.ItemIsEditable


def test_periodic_refresh_does_not_destroy_uncommitted_editor(ui):
    app,w,s,o=ui;w.nav.setCurrentRow(2);t=w.material_table
    t.setCurrentCell(0,2);t.edit(t.model().index(0,2));app.processEvents()
    editor=next(e for e in t.findChildren(QLineEdit) if e.isVisible());editor.setText('not-committed')
    w.refresh();app.processEvents();assert editor.isVisible() and editor.text()=='not-committed'
    QTest.keyClick(editor,Qt.Key.Key_Escape);app.processEvents();assert s.orders()[0]['materials'][0]['name']=='box'


def test_focus_moves_to_other_workspace_commits_plan_input(ui):
    app,w,s,o=ui;w.nav.setCurrentRow(4);t=w.planbook_page.tables[0]
    rect=t.visualRect(t.model().index(1,PLAN_COLUMNS.index('订单数量')))
    QTest.mouseClick(t.viewport(),Qt.MouseButton.LeftButton,pos=rect.center());app.processEvents()
    QTest.keyClick(t,Qt.Key.Key_F2);app.processEvents()
    editor=next(e for e in t.findChildren(QLineEdit) if e.isVisible());editor.setText('16')
    QTest.mouseClick(w.nav.viewport(),Qt.MouseButton.LeftButton,pos=w.nav.visualItemRect(w.nav.item(1)).center());QTest.qWait(10);app.processEvents()
    assert s.orders()[0]['items'][0]['quantity']=='16'
    assert w.pages.currentWidget() is w.order_management_page


def test_order_rename_updates_number_column_and_daily_links(ui):
    app,w,s,o=ui;w.nav.setCurrentRow(1)
    s.save_daily('2026-11-03',{'分仓数据':dict(state='需要跟进',notes='keep',order_ids=[o['id']])})
    m=w.order_management_page;m.table.item(0,0).setText('RENAMED');QTest.qWait(10);app.processEvents()
    assert s.db.execute('SELECT number FROM orders WHERE id=?',(o['id'],)).fetchone()[0]=='RENAMED'
    assert s.daily('2026-11-03')['分仓数据']['order_ids']==[o['id']]
    assert s.orders()[0]['items'][0]['id']==o['items'][0]['id']


def test_f2_opens_editor_without_double_click(ui):
    app,w,s,o=ui;w.nav.setCurrentRow(4);t=w.planbook_page.tables[0]
    t.setCurrentCell(1,PLAN_COLUMNS.index('订单数量'));t.setFocus();QTest.keyClick(t,Qt.Key.Key_F2);app.processEvents()
    editor=next(e for e in t.findChildren(QLineEdit) if e.isVisible());editor.setText('17');QTest.keyClick(editor,Qt.Key.Key_Return);QTest.qWait(10)
    assert s.orders()[0]['items'][0]['quantity']=='17'


@pytest.mark.parametrize('workspace',[1,2,4])
def test_repeated_single_click_only_selects_in_each_grid(ui,workspace):
    app,w,s,o=ui;w.nav.setCurrentRow(workspace)
    t={1:w.order_management_page.table,2:w.material_table,4:w.planbook_page.tables[0]}[workspace]
    row,col=(1,PLAN_COLUMNS.index('订单数量')) if workspace==4 else (0,3 if workspace==1 else 2)
    t.scrollToItem(t.item(row,col));rect=t.visualRect(t.model().index(row,col))
    for _ in range(2):
        QTest.mouseClick(t.viewport(),Qt.MouseButton.LeftButton,pos=rect.center());QTest.qWait(QApplication.doubleClickInterval()+5)
        assert t.state()!=t.State.EditingState
        assert not any(e.isVisible() for e in t.findChildren(QLineEdit))


def test_typing_replaces_original_and_f2_edits_in_place(ui):
    app,w,s,o=ui;w.nav.setCurrentRow(4);t=w.planbook_page.tables[0];col=PLAN_COLUMNS.index('订单数量')
    t.setCurrentCell(1,col);t.setFocus();QTest.keyClick(t,Qt.Key.Key_2);app.processEvents()
    editor=next(e for e in t.findChildren(QLineEdit) if e.isVisible());QTest.keyClicks(editor,'5');QTest.keyClick(editor,Qt.Key.Key_Return);QTest.qWait(10)
    assert s.orders()[0]['items'][0]['quantity']=='25'
    assert t.currentRow()==2 and t.currentColumn()==col
    t.setCurrentCell(1,col);QTest.keyClick(t,Qt.Key.Key_F2);app.processEvents()
    editor=next(e for e in t.findChildren(QLineEdit) if e.isVisible());assert editor.text()=='25' and editor.cursorPosition()==2 and not editor.hasSelectedText()
    QTest.keyClicks(editor,'0');QTest.keyClick(editor,Qt.Key.Key_Return);QTest.qWait(10)
    assert s.orders()[0]['items'][0]['quantity']=='250'


def test_double_click_opens_existing_content(ui):
    app,w,s,o=ui;w.nav.setCurrentRow(4);t=w.planbook_page.tables[0];col=PLAN_COLUMNS.index('订单数量')
    t.scrollToItem(t.item(1,col));rect=t.visualRect(t.model().index(1,col))
    QTest.mouseClick(t.viewport(),Qt.MouseButton.LeftButton,pos=rect.center());QTest.mouseDClick(t.viewport(),Qt.MouseButton.LeftButton,pos=rect.center());app.processEvents()
    editor=next(e for e in t.findChildren(QLineEdit) if e.isVisible());assert editor.text()=='10'
    QTest.keyClick(editor,Qt.Key.Key_Escape);assert s.orders()[0]['items'][0]['quantity']=='10'


def test_enter_tab_select_only_and_shift_reverse_direction(ui):
    app,w,s,o=ui;w.nav.setCurrentRow(4);t=w.planbook_page.tables[0];t.setCurrentCell(1,5);t.setFocus()
    QTest.keyClick(t,Qt.Key.Key_Return);assert (t.currentRow(),t.currentColumn())==(2,5)
    QTest.keyClick(t,Qt.Key.Key_Return,Qt.KeyboardModifier.ShiftModifier);assert (t.currentRow(),t.currentColumn())==(1,5)
    QTest.keyClick(t,Qt.Key.Key_Tab);assert (t.currentRow(),t.currentColumn())==(1,6)
    QTest.keyClick(t,Qt.Key.Key_Backtab,Qt.KeyboardModifier.ShiftModifier);assert (t.currentRow(),t.currentColumn())==(1,5)
    assert not any(e.isVisible() for e in t.findChildren(QLineEdit))


def test_delete_clears_editable_text_but_not_formula(ui):
    app,w,s,o=ui;w.nav.setCurrentRow(4);t=w.planbook_page.tables[0];col=PLAN_COLUMNS.index('备注')
    assert w.planbook_page.commit_cell(0,1,col,'memo');QTest.qWait(10)
    t.setCurrentCell(1,col);t.setFocus();QTest.keyClick(t,Qt.Key.Key_Delete);QTest.qWait(10)
    from openpyxl.utils.cell import get_column_letter
    assert s.planbook()['sheets'][0]['cells'][f'{get_column_letter(col+1)}2']['v']==''
    t.setCurrentCell(1,len(PLAN_COLUMNS));QTest.keyClick(t,Qt.Key.Key_Delete);QTest.qWait(10)
    assert s.planbook()['sheets'][0]['cells'][f'{get_column_letter(len(PLAN_COLUMNS)+1)}2']['f']=='=L2*2'
