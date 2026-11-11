import copy
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QTableWidgetSelectionRange
from openpyxl import load_workbook
from workbench.planbook import export_planbook
from workbench.cell_format import selected_cells
from workbench.storage import Store
from test_inline_edit import ui


def select(table,r1,c1,r2=None,c2=None):
    table.clearSelection();table.setCurrentCell(r1,c1)
    table.setRangeSelected(QTableWidgetSelectionRange(r1,c1,r1 if r2 is None else r2,c1 if c2 is None else c2),True)


def test_batch_format_formula_empty_cell_undo_redo_and_export(ui,tmp_path):
    app,w,s,o=ui;w.nav.setCurrentRow(4);p=w.planbook_page;t=p.tables[0]
    before=copy.deepcopy(s.planbook());formula_col=t.columnCount()-1
    select(t,1,formula_col,2,formula_col)
    p.formatter.apply(dict(family='Microsoft YaHei',size=18,bold=True,italic=True,underline=True,
        foreground='#ff0000',background='#ffff00',horizontal='center',vertical='top',wrap=False))
    assert len(w.edit_history.undo_stack)==1
    assert s.orders()[0]['items'][0]['quantity']=='10'
    sheet=s.planbook()['sheets'][0]
    assert sheet['cells']==before['sheets'][0]['cells'] and sheet['edits']=={}
    assert 'f' in sheet['cells'][f'{t.horizontalHeaderItem(formula_col).text()}2']
    assert t.item(1,formula_col).font().pointSizeF()==18 and t.item(1,formula_col).font().underline()
    assert not t.item(1,formula_col).flags() & Qt.ItemFlag.ItemIsEditable
    app.processEvents();image=t.viewport().grab().toImage();rect=t.visualItemRect(t.item(1,formula_col))
    target=tmp_path/'out.xlsx';export_planbook(target,s.planbook(),s.planbook_source())
    book=load_workbook(target);cell=book.worksheets[0].cell(2,formula_col+1);blank=book.worksheets[0].cell(3,formula_col+1)
    assert cell.value=='=L2*2' and cell.font.sz==18 and cell.font.b and cell.font.i and cell.font.u=='single'
    assert cell.font.color.rgb=='FFFF0000' and cell.fill.fgColor.rgb=='FFFFFF00'
    assert cell.alignment.horizontal=='center' and cell.alignment.vertical=='top' and cell.alignment.wrap_text is False
    assert blank.value is None and blank.font.sz==18
    book.close();w.replay_edit();app.processEvents()
    assert not s.planbook()['sheets'][0].get('format_edits')
    assert not s.planbook()['sheets'][0].get('formulas_stale')
    w.replay_edit(True);app.processEvents();assert s.planbook()['sheets'][0]['format_edits']


def test_merged_selection_is_one_anchor_and_reset_restores_original(ui):
    app,w,s,o=ui;w.nav.setCurrentRow(4);p=w.planbook_page;p.tabs.setCurrentIndex(1);t=p.tables[1]
    select(t,2,0,3,0);assert selected_cells(t,p.payload['sheets'][1])==[(3,1)]
    p.formatter.apply({'size':22,'bold':True});assert list(s.planbook()['sheets'][1]['format_edits'])==['A3']
    p.formatter.apply(reset=True);assert not s.planbook()['sheets'][1]['format_edits']
    w.replay_edit();app.processEvents();assert p.tables[1].item(2,0).font().pointSizeF()==22


def test_plan_header_drag_dimensions_survive_reload_undo_and_export(ui,tmp_path):
    app,w,s,o=ui;w.nav.setCurrentRow(4);p=w.planbook_page;t=p.tables[0];select(t,1,1);old=t.columnWidth(1)
    t.setColumnWidth(1,240);QTest.qWait(300);app.processEvents()
    assert s.planbook()['sheets'][0]['dimension_edits']['columns']['2']==240
    assert len(w.edit_history.undo_stack)==1
    w.replay_edit();app.processEvents();assert p.tables[0].columnWidth(1)==old
    w.replay_edit(True);app.processEvents();assert p.tables[0].columnWidth(1)==240
    select(p.tables[0],1,1,2,1);p.formatter.resize_selected('rows',80)
    assert p.tables[0].rowHeight(1)==80 and p.tables[0].rowHeight(2)==80
    target=tmp_path/'sized.xlsx';export_planbook(target,s.planbook(),s.planbook_source());book=load_workbook(target)
    assert book.active.row_dimensions[2].height==60 and book.active.column_dimensions['B'].width==28.5
    book.close()


def test_shortcut_bold_size_and_wrap_controls(ui):
    app,w,s,o=ui;w.nav.setCurrentRow(4);p=w.planbook_page;t=p.tables[0];select(t,1,1);t.setFocus();app.processEvents()
    QTest.keyClick(t,Qt.Key.Key_B,Qt.KeyboardModifier.ControlModifier);app.processEvents()
    assert t.item(1,1).font().bold() and s.planbook()['sheets'][0]['format_edits']['B2']['bold']
    p.format_bar.size.setValue(20);p.format_bar.size.editingFinished.emit()
    assert t.item(1,1).font().pointSizeF()==20
    p.formatter.apply({'wrap':False});p.formatter.resize_selected('columns',60);p.formatter.fit('columns')
    assert s.planbook()['sheets'][0]['dimension_edits']['columns']['2']>32


def test_order_and_material_formats_survive_refresh_and_undo_without_data_changes(ui,tmp_path):
    app,w,s,o=ui;w.nav.setCurrentRow(1);m=w.order_management_page;t=m.table;before=s.orders()
    select(t,0,1,1,1);m.formatter.apply({'size':16,'bold':True,'background':'#ffccee','horizontal':'center'})
    w.refresh();app.processEvents();assert t.item(0,1).font().pointSizeF()==16 and t.item(1,1).font().bold()
    assert s.orders()==before and len(w.edit_history.undo_stack)==1
    w.replay_edit();app.processEvents();assert not s.table_format('orders').get('cells')
    assert t.item(0,1).font().pointSizeF()!=16
    w.replay_edit(True);app.processEvents();assert t.item(0,1).background().color()==QColor('#ffccee')
    old=t.columnWidth(1);select(t,0,1);m.formatter.resize_selected('columns',200)
    w.replay_edit();app.processEvents();assert t.columnWidth(1)==old
    w.nav.setCurrentRow(2);select(w.material_table,0,2);w.material_formatter.apply({'foreground':'#aa0000','underline':True})
    assert w.material_table.item(0,2).font().underline() and s.orders()==before
    backup=tmp_path/'backup.json';s.export_json(backup);s.save_table_format('orders',{});s.restore_json(backup)
    assert s.table_format('orders')['cells'] and s.table_format('materials')['cells']


def test_view_format_does_not_follow_another_order_after_filtering(ui):
    from workbench.domain import new_order,new_item
    app,w,s,o=ui;w.nav.setCurrentRow(1);m=w.order_management_page;select(m.table,0,1);m.formatter.apply({'size':25})
    other=new_order();other.update(number='OTHER',items=[new_item('OTHER-MODEL','2')]);s.save_order(other);w.refresh()
    m.search.setText('OTHER');app.processEvents();assert m.table.item(0,1).font().pointSizeF()!=25
    m.search.setText('INLINE');app.processEvents();assert m.table.item(0,1).font().pointSizeF()==25


def test_header_double_click_autofit_is_one_undoable_action(ui):
    from PySide6.QtCore import QPoint
    app,w,s,o=ui;w.nav.setCurrentRow(4);p=w.planbook_page;t=p.tables[0];select(t,1,1)
    p.formatter.resize_selected('columns',240);before=len(w.edit_history.undo_stack);header=t.horizontalHeader()
    point=QPoint(header.sectionViewportPosition(1)+header.sectionSize(1)-1,header.height()//2)
    QTest.mouseDClick(header.viewport(),Qt.MouseButton.LeftButton,pos=point);QTest.qWait(300);app.processEvents()
    assert t.columnWidth(1)!=240 and len(w.edit_history.undo_stack)==before+1
    w.replay_edit();QTest.qWait(300);app.processEvents();assert p.tables[0].columnWidth(1)==240
