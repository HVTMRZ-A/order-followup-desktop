from datetime import date,datetime,timedelta
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtGui import QColor
from workbench.ux_controls import OrderSelectionDialog
from workbench.production import PLAN_COLUMNS
from test_inline_edit import ui
from test_cell_format import select


def test_format_tools_collapse_and_remember_preference(ui):
    app,w,s,o=ui;w.nav.setCurrentRow(4);p=w.planbook_page;app.processEvents();height=p.tables[0].height()
    assert p.format_bar.isHidden() and not p.format_toggle.isChecked()
    QTest.mouseClick(p.format_toggle,Qt.MouseButton.LeftButton);app.processEvents()
    assert not p.format_bar.isHidden() and p.tables[0].height()<height and s.get('format_tools_open_plan')=='1'
    QTest.mouseClick(p.format_toggle,Qt.MouseButton.LeftButton);app.processEvents()
    assert p.tables[0].height()>=height and s.get('format_tools_open_plan')=='0'
    assert w.order_management_page.format_bar.isHidden() and w.material_format_bar.isHidden()


def test_current_value_full_text_formula_and_undo_from_readonly_bar(ui):
    app,w,s,o=ui;w.nav.setCurrentRow(4);p=w.planbook_page;t=p.tables[0];select(t,1,PLAN_COLUMNS.index('规格型号'))
    assert p.cell_value.text()=='230V' and p.cell_value.isReadOnly()
    text='长内容 '*70;assert p.commit_cell(0,1,PLAN_COLUMNS.index('备注'),text);select(t,1,PLAN_COLUMNS.index('备注'))
    assert p.cell_value.text()==text and 'AE2' in p.cell_address.text()
    p.cell_value.setFocus();w.replay_edit();app.processEvents();assert s.planbook()['sheets'][0]['cells'].get('AE2',{}).get('v')!=text
    select(p.tables[0],1,len(PLAN_COLUMNS));assert p.cell_value.text()=='=L2*2' and '只读' in p.cell_address.text()


def test_today_search_priority_and_direct_process_preserve_selection(ui):
    app,w,s,o=ui;w.nav.setCurrentRow(0);order=s.orders()[0];order['received_at']=(datetime.now()-timedelta(days=2)).isoformat();s.save_order(order);w.refresh()
    w.todo_filter.setCurrentIndex(1);assert w.todo.rowCount()==1 and '合同' in w.todo.item(0,4).text()
    w.todo_filter.setCurrentIndex(0);w.todo_search.setText('BOM');assert w.todo.rowCount()==1
    w.todo.setCurrentCell(0,4);assert w.todo_process.isEnabled() and 'BOM' in w.todo_selection.text()
    w.refresh();assert w.todo.currentRow()==0 and 'BOM' in w.todo_selection.text()
    w.process_selected_todo();assert all(i['bom'] for i in s.orders()[0]['items'])
    assert w.todo.rowCount()==0 and '匹配' in w.empty.text() and not w.todo_process.isEnabled()


def test_material_search_overdue_and_selected_context(ui):
    app,w,s,o=ui;w.nav.setCurrentRow(2);order=s.orders()[0];order['materials'][0]['due_date']=(date.today()-timedelta(days=1)).isoformat();s.save_order(order);w.refresh()
    w.material_search.setText('box');w.material_filter.setCurrentIndex(3);assert w.material_table.rowCount()==1
    w.material_table.setCurrentCell(0,2);w.show_material_selection();assert 'INLINE-1' in w.material_selection.text() and '19' in w.material_selection.text()
    w.material_search.setText('不存在');assert w.material_table.rowCount()==0 and not w.material_detail_button.isEnabled()
    w.material_search.clear();order=s.orders()[0];order['materials'][0]['arrived']='20';s.save_order(order);w.refresh();assert w.material_table.rowCount()==0


def test_order_picker_keeps_hidden_checked_and_daily_relation(ui,monkeypatch):
    app,w,s,o=ui;orders=s.orders();d=OrderSelectionDialog(orders,[o['id']],w)
    d.search.setText('找不到');assert d.list.item(0).isHidden();d.confirm();assert d.selected_ids==[o['id']]
    def accept(dialog):dialog.selected_ids=[o['id']];return 1
    monkeypatch.setattr(OrderSelectionDialog,'exec',accept);w.choose_daily_orders('分仓数据')
    assert w.daily_order_links['分仓数据'].text()=='INLINE-1' and s.daily(w.current_daily_day)['分仓数据']['order_ids']==[o['id']]


def test_selected_cell_border_is_visible(ui):
    app,w,s,o=ui;w.nav.setCurrentRow(4);w.planbook_page.tabs.setCurrentIndex(0);t=w.planbook_page.tables[0];select(t,1,1);app.processEvents();t.scrollToItem(t.item(1,1));app.processEvents()
    rect=t.visualRect(t.model().index(1,1));snapshot=t.viewport().grab();image=snapshot.toImage();scale=snapshot.devicePixelRatio()
    pixels=[image.pixelColor(round((rect.left()+x)*scale),round(rect.center().y()*scale)) for x in range(1,5)]
    assert any(c==QColor('#245dce') for c in pixels),(rect,scale,[c.name() for c in pixels])


def test_import_lands_on_new_order_without_legacy_export_or_success_popup(ui,monkeypatch):
    from PySide6.QtWidgets import QPushButton,QMessageBox
    from workbench.ui import ImportPreviewDialog
    from workbench.domain import new_order,new_item
    app,w,s,o=ui;order=new_order();order.update(number='NEW-UX-ORDER',items=[new_item('UX-MODEL','3')])
    d=ImportPreviewDialog([order],s,w,'体验.xlsx')
    assert not any('导入并导出' in b.text() for b in d.findChildren(QPushButton))
    monkeypatch.setattr(ImportPreviewDialog,'exec',lambda dialog:1);monkeypatch.setattr(w,'confirm_plan_join',lambda orders:None)
    def unexpected(*a,**k):raise AssertionError('不应弹出额外的成功确认框')
    monkeypatch.setattr(QMessageBox,'information',unexpected)
    w.confirm_import([order],'体验.xlsx');assert w.nav.currentRow()==1
    assert w.order_management_page.table.rowCount()==1 and w.order_management_page.selected()['number']=='NEW-UX-ORDER'


def test_view_order_detail_does_not_unexpectedly_open_plan_join(ui,monkeypatch):
    app,w,s,o=ui;w.nav.setCurrentRow(0);called=[]
    monkeypatch.setattr(w,'edit_order',lambda order:called.append(order['id']))
    monkeypatch.setattr(w,'confirm_plan_join',lambda *a:called.append('plan-join'))
    row=next(r for r in range(w.todo.rowCount()) if w.todo.item(r,4).data(Qt.ItemDataRole.UserRole+2) and w.todo.item(r,4).data(Qt.ItemDataRole.UserRole+2)[4]=='待确认加入计划总表')
    w.todo.setCurrentCell(row,4);assert w.todo_process.text()=='确认加入计划总表'
    w.open_selected_todo_detail();assert called==[o['id']]
