import copy
import os
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font
from PySide6.QtWidgets import QApplication, QWidget, QStyleOptionViewItem
from workbench.planbook import read_planbook, edit_cell, export_planbook
from workbench.plan_layout import ensure_layout, anchor_cell, order_groups
from workbench.plan_ui import PlanBookWidget
from workbench.storage import Store


def make_book(path):
    book = Workbook()
    sheet = book.active
    sheet.title = '整体配件汇总'
    sheet['A1'] = '订单汇总'
    sheet.merge_cells('A1:H1')
    sheet['A1'].alignment = Alignment(horizontal='center', vertical='center')
    sheet['A1'].font = Font(size=16, bold=True)
    sheet.row_dimensions[1].height = 36
    sheet.column_dimensions['D'].width = 22
    sheet.append(['月份', '客户', '经办人', '订单号', '公司型号', '数量', '计算'])
    for row in [['5月', 'C1', '甲', 'ORDER-1', 'A', 2, '=F3*2'],
                [None, None, None, None, 'B', 3],
                [None, 'C2', '乙', 'ORDER-2', 'C', 5],
                [None, None, None, None, 'D', 7],
                [None, None, None, None, '未关联明细', 1]]:
        sheet.append(row)
    sheet.merge_cells('A3:A6')
    for col in 'BCD':
        sheet.merge_cells(f'{col}3:{col}4')
        sheet.merge_cells(f'{col}5:{col}6')
    book.save(path)
    return read_planbook(path)


def test_layout_reads_merged_title_dimensions_styles_and_preserves_export(tmp_path):
    source = tmp_path/'source.xlsx'
    p, blob = make_book(source)
    sheet = p['sheets'][0]
    assert sheet['cols'] == 8  # 最右列来自标题的合并范围，不是非空单元格。
    assert 'A1:H1' in sheet['layout']['merges']
    assert sheet['layout']['heights']['1'] == 36
    assert any(c['first'] == 4 and c['width'] == 22 for c in sheet['layout']['columns'])
    assert p['display_styles'][sheet['cells']['A1']['s']]['bold']
    assert anchor_cell(sheet, 4, 4) == (3, 4)
    edit_cell(sheet, 'F4', 10)
    target = tmp_path/'out.xlsx'
    export_planbook(target, p, blob)
    book = load_workbook(target)
    out = book.active
    assert 'A1:H1' in {str(r) for r in out.merged_cells.ranges}
    assert out['F4'].value == 10 and out['G3'].value == '=F3*2'
    assert out['A1'].alignment.horizontal == 'center' and out['A1'].font.bold
    assert out.column_dimensions['D'].width == 22
    book.close()
    assert source.read_bytes() == blob


def test_groups_use_explicit_order_merges_and_keep_unassigned_row_separate(tmp_path):
    p, _ = make_book(tmp_path/'source.xlsx')
    groups, cols, header = order_groups(p['sheets'][0])
    assert header == 2 and cols['订单号'] == 4
    assert [(g['number'], g['start'], g['end']) for g in groups] == [('ORDER-1', 3, 4), ('ORDER-2', 5, 6)]
    assert '5月' in groups[1]['context']  # 跨订单的月份合并仍可被检索。


def test_merged_edit_and_partial_deletion_keep_shared_parent_data(tmp_path):
    from workbench.order_changes import detach_plan
    p, _ = make_book(tmp_path/'source.xlsx')
    sheet = p['sheets'][0]
    edit_cell(sheet, 'D4', 'ORDER-NEW')
    assert sheet['cells']['D3']['v'] == 'ORDER-NEW' and 'D4' not in sheet['edits']
    p['order_links'] = [dict(order_id='o1', item_id='A', sheet=sheet['name'], row=3),
                        dict(order_id='o1', item_id='B', sheet=sheet['name'], row=4)]
    result = detach_plan(p, 'o1', {'B'}, clear_rows=True)
    assert result['sheets'][0]['cells']['D3']['v'] == 'ORDER-NEW'
    assert result['sheets'][0]['cells']['E4']['v'] == ''
    result = detach_plan(p, 'o1', {'A', 'B'}, clear_rows=True)
    assert result['sheets'][0]['cells']['D3']['v'] == ''
    assert result['sheets'][0]['cells']['A3']['v'] == '5月'  # 月份还与其他订单共用。


def test_linked_merged_order_change_requires_review_for_each_child(tmp_path):
    from workbench.domain import new_order, new_item
    from workbench.plan_sync import build_preview, apply_preview
    p, _ = make_book(tmp_path/'source.xlsx')
    order = new_order()
    order['number'] = 'ORDER-NEW'
    order['items'] = [new_item('A', '2'), new_item('B', '3')]
    p['order_links'] = [dict(order_id=order['id'], item_id=item['id'], sheet='整体配件汇总', row=n+3) for n,item in enumerate(order['items'])]
    rows = build_preview(p, [order], ['整体配件汇总'])
    assert all(r['state'] == '待更新关联行' for r in rows)
    result, _, count = apply_preview(p, [order], ['整体配件汇总'], set())
    assert count == 0 and result['sheets'][0]['cells']['D3']['v'] == 'ORDER-1'
    result, _, count = apply_preview(p, [order], ['整体配件汇总'], {rows[1]['key']})
    assert count == 1 and result['sheets'][0]['cells']['D3']['v'] == 'ORDER-NEW'
    assert 'D4' not in result['sheets'][0]['edits']


def test_old_saved_payload_gains_layout_without_losing_edits_or_links(tmp_path):
    p, blob = make_book(tmp_path/'source.xlsx')
    p.pop('display_styles')
    p['sheets'][0].pop('layout')
    edit_cell(p['sheets'][0], 'F4', 99)
    p['order_links'] = [dict(order_id='o1', item_id='i1', sheet='整体配件汇总', row=4)]
    cells = copy.deepcopy(p['sheets'][0]['cells'])
    edits = copy.deepcopy(p['sheets'][0]['edits'])
    links = copy.deepcopy(p['order_links'])
    assert ensure_layout(p, blob)
    assert p['sheets'][0]['cells'] == cells and p['sheets'][0]['edits'] == edits and p['order_links'] == links
    assert not ensure_layout(p, blob)


def test_ui_merged_parent_child_search_and_old_data_upgrade(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    app = QApplication.instance() or QApplication([])
    p, blob = make_book(tmp_path/'source.xlsx')
    p.pop('display_styles')
    p['sheets'][0].pop('layout')
    p['order_links'] = [dict(order_id='o1', item_id='i2', sheet='整体配件汇总', row=4)]
    store = Store(tmp_path/'db')
    store.save_planbook(p, blob)
    parent = QWidget()
    parent.workers = []
    w = PlanBookWidget(store, parent)
    table = w.tables[0]
    assert table.columnSpan(0, 0) == 8 and table.rowSpan(2, 3) == 2
    assert table.rowHeight(0) == 48 and table.columnWidth(3) > 150
    assert store.planbook()['sheets'][0]['layout']['merges']
    table.setCurrentCell(3, 4)
    assert w.selected_link()['item_id'] == 'i2'
    assert 'ORDER-1' in w.relationship.text() and '2 行' in w.relationship.text()
    option = QStyleOptionViewItem()
    table.itemDelegate().initStyleOption(option, table.model().index(3, 4))
    assert option.text == '└─ B' and table.item(3, 4).text() == 'B'
    w.search.setText('B')
    assert not table.isRowHidden(0) and not table.isRowHidden(1)
    assert not table.isRowHidden(2) and not table.isRowHidden(3)
    assert table.isRowHidden(4) and table.isRowHidden(5)
    w.search.setText('5月')
    assert all(not table.isRowHidden(r) for r in range(2, 6))
    assert table.isRowHidden(6)  # 空订单号的记录不会凭空归入前一订单。
    w.close()
    store.db.close()
