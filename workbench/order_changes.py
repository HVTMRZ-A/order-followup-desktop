"""删除时解除关联并保留回收记录；计划表不移动行号，保护公式引用。"""
import copy
from openpyxl.utils.cell import coordinate_to_tuple
from .planbook import edit_cell
from .plan_layout import merge_ranges


def remove_model(order, item_id):
    result = copy.deepcopy(order)
    item = next((i for i in result['items'] if i['id'] == item_id), None)
    if item is None:
        raise ValueError('所选型号已不存在，请刷新后重试。')
    if len(result['items']) == 1:
        raise ValueError('这是订单的最后一个型号，请使用“删除整单”。')
    result['items'] = [i for i in result['items'] if i['id'] != item_id]
    result['materials'] = [m for m in result.get('materials', []) if m['item_id'] != item_id]
    prefix = f"{order['id']}:{item_id}:"
    result['plan_pending'] = [p for p in result.get('plan_pending', []) if not p.get('key', '').startswith(prefix)]
    result['plan_overrides'] = {k: v for k, v in result.get('plan_overrides', {}).items() if not k.startswith(prefix)}
    result['plan_sync_checked'] = False
    return result


def detach_plan(payload, order_id, item_ids, clear_rows=False):
    if payload is None:
        return None
    result = copy.deepcopy(payload)
    links = result.get('order_links', [])
    removed = [l for l in links if l['order_id'] == order_id and l['item_id'] in item_ids]
    result['order_links'] = [l for l in links if l not in removed]
    if clear_rows:
        shared = {(l['sheet'], l['row']) for l in result['order_links']}
        affected = {(l['sheet'], l['row']) for l in removed} - shared
        for sheet in result['sheets']:
            rows = {row for name, row in affected if name == sheet['name']}
            for address, cell in list(sheet['cells'].items()):
                row,col=coordinate_to_tuple(address)
                shared=any(left<=col<=right and top<=row<=bottom and not set(range(top,bottom+1))<=rows for left,top,right,bottom in merge_ranges(sheet))
                if row in rows and 'f' not in cell and not shared:
                    edit_cell(sheet, address, '')
        if affected:
            for sheet in result['sheets']:
                sheet['formulas_stale'] = True
    return result


def refresh_overrides(previous, updated):
    """订单编辑后去掉过期的加入预览值，保留人工填入的采购/出货资料。"""
    if not updated.get('plan_overrides'):
        return
    from .plan_sync import build_preview, TARGETS, equivalent
    before, after = copy.deepcopy(previous), copy.deepcopy(updated)
    before.pop('plan_overrides', None)
    after.pop('plan_overrides', None)
    keys = [key.split(':', 2) for key in updated['plan_overrides']]
    item_ids = {parts[1] for parts in keys if len(parts) == 3}
    targets = [name for name in TARGETS if any(len(parts) == 3 and parts[2] == name for parts in keys)]
    before['items'] = [i for i in before['items'] if i['id'] in item_ids]
    after['items'] = [i for i in after['items'] if i['id'] in item_ids]
    old_rows = {r['key']: r['values'] for r in build_preview(None, [before], targets)}
    for row in build_preview(None, [after], targets):
        overrides = updated['plan_overrides'].get(row['key'], {})
        old = old_rows.get(row['key'], {})
        for field, value in row['values'].items():
            if not equivalent(old.get(field), value):
                overrides.pop(field, None)
