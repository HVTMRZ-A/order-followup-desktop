import json
from pathlib import Path
import pytest
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
from openpyxl import Workbook, load_workbook
from workbench.domain import new_order, new_item, demand
from workbench.storage import Store
from workbench.planbook import read_planbook, export_planbook
from workbench.plan_sync import build_preview, apply_preview
from workbench.ui import MainWindow, OrderDialog, ItemDialog
from workbench.order_editing import DeleteOrderDialog, OrderTrashDialog


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('ORDER_WORKBENCH_DATA', str(tmp_path / 'data'))
    app = QApplication.instance() or QApplication([])
    s = Store(tmp_path / 'db')
    o = new_order()
    o.update(number='EDIT-1', customer='保留客户', source_original_b64='c291cmNl')
    o['items'] = [new_item('A', '10'), new_item('B', '20')]
    o['items'][1]['material_code'] = '001.002'
    o['materials'] = [dict(id='mA', item_id=o['items'][0]['id'], name='纸箱A', usage='2', arrived='0'),
                      dict(id='mB', item_id=o['items'][1]['id'], name='纸箱B', usage='3', arrived='0')]
    o['plan_pending'] = [dict(key=f"{o['id']}:{i['id']}:最新", model=i['model'], sheet='最新', reason='待补充') for i in o['items']]
    s.save_order(o)
    b = Workbook()
    b.active.title = '最新'
    b.active.append(['订单号', '产品型号', '订单数量', '物料编码', '备注', '合计'])
    b.active.append([o['number'], 'A', 10, '', '计划备注A', '=C2*2'])
    b.active.append([o['number'], 'B', 20, '001.002', '计划备注B', '=C3*2'])
    path = tmp_path / 'plan.xlsx'
    b.save(path)
    p, blob = read_planbook(path)
    p['order_links'] = [dict(order_id=o['id'], item_id=i['id'], sheet='最新', row=n+2) for n, i in enumerate(o['items'])]
    s.save_planbook(p, blob)
    s.save_daily('2026-11-02', {'分仓数据': dict(state='需要跟进', notes='保留说明', order_ids=[o['id'], 'other'])})
    yield app, s, o
    s.db.close()


def close(w):
    w.quitting = True
    w.close()
    w.timer.stop()
    w.tray.hide()


def test_delete_one_model_removes_only_its_materials_pending_and_links(setup):
    _, s, o = setup
    deleted = s.delete_order(o['id'], o['items'][1]['id'])
    saved = s.orders()[0]
    assert [i['model'] for i in saved['items']] == ['A']
    assert [m['id'] for m in saved['materials']] == ['mA']
    assert all(p['model'] != 'B' for p in saved['plan_pending'])
    assert len(s.planbook()['order_links']) == 1
    assert s.planbook()['sheets'][0]['cells']['B3']['v'] == 'B'
    assert s.daily('2026-11-02')['分仓数据']['order_ids'] == [o['id'], 'other']
    record = s.trash()[0]
    assert record['id'] == deleted and Path(record['backup']).is_file()
    # 恢复只合并被删除的型号，保留其余型号及订单的后续编辑。
    saved['items'][0]['quantity'] = '99'
    saved['customer'] = '后续编辑'
    s.save_order(saved)
    restored = s.restore_deleted(deleted)
    assert restored['customer'] == '后续编辑'
    assert [i['quantity'] for i in restored['items']] == ['99', '20']
    assert restored['items'][1]['material_code'] == '001.002'
    assert len(restored['materials']) == 2 and not restored['plan_sync_checked']
    assert s.trash() == []


def test_delete_entire_order_clears_chosen_plan_inputs_but_keeps_formulas_and_history(setup, tmp_path):
    _, s, o = setup
    other = new_order()
    other['number'] = 'OTHER'
    other['items'] = [new_item('KEEP', '5')]
    s.save_order(other)
    identity = s.delete_order(o['id'], clear_plan_rows=True)
    assert [x['number'] for x in s.orders()] == ['OTHER']
    p = s.planbook()
    assert not p['order_links']
    assert p['sheets'][0]['cells']['A2']['v'] == ''
    assert p['sheets'][0]['cells']['E3']['v'] == ''
    assert p['sheets'][0]['cells']['F3']['f'] == '=C3*2'
    assert p['sheets'][0]['rows'] == 3
    assert s.daily('2026-11-02')['分仓数据'] == dict(state='需要跟进', notes='保留说明', order_ids=['other'])
    output = tmp_path / 'out.xlsx'
    export_planbook(output, p, s.planbook_source())
    b = load_workbook(output)
    assert b.active['A2'].value is None and b.active['F2'].value == '=C2*2'
    b.close()
    restored = s.restore_deleted(identity)
    assert restored['source_original_b64'] == o['source_original_b64']
    assert restored['materials'] == o['materials']
    assert s.planbook()['order_links'] == []  # 不覆盖删除后编辑的计划或每日记录。
    assert s.planbook()['sheets'][0]['cells']['A2']['v'] == ''


def test_shared_plan_row_is_not_cleared(setup):
    _, s, o = setup
    p = s.planbook()
    p['order_links'].append(dict(order_id='other', item_id='other-item', sheet='最新', row=2))
    s.save_planbook(p)
    s.delete_order(o['id'], clear_plan_rows=True)
    assert s.planbook()['sheets'][0]['cells']['A2']['v'] == o['number']
    assert s.planbook()['order_links'][0]['order_id'] == 'other'


def test_last_model_guard_and_restore_conflicts_do_not_change_data(setup):
    _, s, o = setup
    first = s.delete_order(o['id'], o['items'][1]['id'])
    with pytest.raises(ValueError, match='最后一个型号'):
        s.delete_order(o['id'], o['items'][0]['id'])
    whole = s.delete_order(o['id'])
    with pytest.raises(ValueError, match='先从回收站恢复整单'):
        s.restore_deleted(first)
    s.restore_deleted(whole)
    s.restore_deleted(first)
    with pytest.raises(ValueError, match='已恢复'):
        s.restore_deleted(first)
    whole = s.delete_order(o['id'])
    duplicate = new_order()
    duplicate['number'] = o['number']
    duplicate['items'] = [new_item('DUP', '5')]
    s.save_order(duplicate)
    with pytest.raises(ValueError, match='相同订单号'):
        s.restore_deleted(whole)
    assert s.orders()[0]['items'][0]['model'] == 'DUP'
    assert len(s.trash()) == 1


def test_deletion_and_all_associations_roll_back_on_failure(setup):
    _, s, o = setup
    before_plan = s.planbook()
    before_daily = s.daily_all()
    s.db.execute("CREATE TRIGGER block_delete BEFORE DELETE ON orders BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    with pytest.raises(Exception, match='test failure'):
        s.delete_order(o['id'], clear_plan_rows=True)
    assert len(s.orders()) == 1 and s.trash() == []
    assert s.planbook() == before_plan and s.daily_all() == before_daily


def test_recycle_bin_is_in_json_backup_and_old_backup_remains_compatible(setup, tmp_path):
    _, s, o = setup
    identity = s.delete_order(o['id'], o['items'][0]['id'])
    p = tmp_path / 'backup.json'
    s.export_json(p)
    s.restore_deleted(identity)
    s.restore_json(p)
    assert len(s.orders()[0]['items']) == 1 and s.trash()[0]['id'] == identity
    s.restore_deleted(identity)
    data = json.loads(p.read_text(encoding='utf-8'))
    data.pop('order_trash')
    p.write_text(json.dumps(data), encoding='utf-8')
    s.restore_json(p)
    assert s.trash() == []


def test_direct_edit_keeps_selected_model_identity_and_updates_quantity_plan_preview(setup, monkeypatch):
    app, s, o = setup
    w = MainWindow(s)
    m = w.order_management_page
    m.table.setCurrentCell(1, 0)
    m.refresh()
    assert m.selected_item()['model'] == 'B'
    def edit(dialog):
        dialog.model.setText('B-NEW')
        dialog.qty.setText('30')
        dialog.extra_fields['material_code'].setText('001.003')
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(ItemDialog, 'exec', edit)
    joined = []
    monkeypatch.setattr(w, 'confirm_plan_join', lambda orders: joined.extend(orders))
    m.edit_selected_item()
    saved = s.orders()[0]
    assert saved['items'][1]['id'] == o['items'][1]['id']
    assert saved['items'][1]['model'] == 'B-NEW' and saved['items'][1]['quantity'] == '30'
    assert demand(saved, saved['materials'][1]) == 90
    assert saved['source_original_b64'] == o['source_original_b64']
    assert joined[0]['id'] == o['id']
    rows = build_preview(s.planbook(), [saved], ['最新'])
    assert rows[1]['state'] == '待更新关联行'
    assert s.planbook()['sheets'][0]['cells']['C3']['v'] == 20
    p, _, n = apply_preview(s.planbook(), [saved], ['最新'], {rows[1]['key']})
    assert n == 1 and p['sheets'][0]['cells']['B3']['v'] == 'B-NEW'
    assert p['sheets'][0]['cells']['C3']['v'] == 30
    close(w)


def test_existing_plan_overrides_cannot_hide_later_order_edits(setup):
    _, s, o = setup
    key = f"{o['id']}:{o['items'][1]['id']}:最新"
    saved = s.orders()[0]
    saved['plan_overrides'] = {key: {'订单号': o['number'], '产品型号': 'B', '订单数量': '20', '物料编码': '001.002', '备注': '人工补充保留'}}
    s.save_plan_join(s.planbook(), [saved])
    saved['number'] = 'EDIT-NEW'
    saved['items'][1].update(model='B-NEW', quantity='50', material_code='001.003')
    s.save_order(saved)
    row = build_preview(s.planbook(), s.orders(), ['最新'])[1]
    assert row['values']['订单号'] == 'EDIT-NEW' and row['values']['产品型号'] == 'B-NEW'
    assert row['values']['订单数量'] == 50 and row['values']['物料编码'] == '001.003'
    assert row['values']['备注'] == '人工补充保留'


def test_manager_cancel_delete_then_confirm_and_restore(setup, monkeypatch):
    app, s, o = setup
    w = MainWindow(s)
    manager = w.order_management_page
    manager.table.setCurrentCell(1, 0)
    monkeypatch.setattr(DeleteOrderDialog, 'exec', lambda self: QDialog.DialogCode.Rejected)
    manager.delete_selected_item()
    assert len(s.orders()[0]['items']) == 2 and not s.trash()
    monkeypatch.setattr(DeleteOrderDialog, 'exec', lambda self: QDialog.DialogCode.Accepted)
    manager.delete_selected_item()
    assert [i['model'] for i in s.orders()[0]['items']] == ['A']
    assert manager.table.rowCount() == 1 and w.material_table.rowCount() == 1
    trash = OrderTrashDialog(w)
    trash.table.setCurrentCell(0, 0)
    trash.restore_selected()
    assert manager.table.rowCount() == 2 and w.material_table.rowCount() == 2
    assert trash.table.rowCount() == 0
    manager.table.setCurrentCell(1, 0)
    manager.delete_selected_order()
    assert manager.table.rowCount() == 0 and w.material_table.rowCount() == 0
    assert all(not b.isEnabled() for b in manager.selection_buttons)
    w.daily_date.setDate(QDate(2026, 11, 2))
    assert w.daily_order_links['分仓数据'].text() == 'other'
    trash.reject()
    close(w)


def test_order_dialog_model_removal_is_staged_and_saved_to_recycle_bin(setup, monkeypatch):
    app, s, o = setup
    w = MainWindow(s)
    monkeypatch.setattr(DeleteOrderDialog, 'exec', lambda self: QDialog.DialogCode.Accepted)
    d = OrderDialog(s, s.orders()[0], w)
    d.items.setCurrentCell(1, 0)
    d.remove_item()
    assert len(d.order['items']) == 1 and len(d.order['materials']) == 1
    d.reject()
    assert len(s.orders()[0]['items']) == 2 and s.trash() == []
    d = OrderDialog(s, s.orders()[0], w)
    d.items.setCurrentCell(1, 0)
    d.remove_item()
    d.save()
    assert d.saved and len(s.orders()[0]['items']) == 1
    assert s.trash()[0]['item_id'] == o['items'][1]['id']
    assert len(s.planbook()['order_links']) == 1
    close(w)


@pytest.mark.parametrize('model,quantity', [('A', '30'), ('B', '0'), ('', '10')])
def test_invalid_model_edits_leave_saved_order_and_plan_unchanged(setup, monkeypatch, model, quantity):
    app, s, o = setup
    w = MainWindow(s)
    before_order, before_plan = s.orders(), s.planbook()
    w.order_management_page.table.setCurrentCell(1, 0)
    def edit(dialog):
        dialog.model.setText(model)
        dialog.qty.setText(quantity)
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(ItemDialog, 'exec', edit)
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args[2]))
    monkeypatch.setattr(w, 'confirm_plan_join', lambda *args: pytest.fail('保存失败不应继续更新计划表'))
    w.order_management_page.edit_selected_item()
    assert warnings and s.orders() == before_order and s.planbook() == before_plan
    close(w)
