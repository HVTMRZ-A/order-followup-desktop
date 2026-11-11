"""计划内容批量清空及记录移除；保持原行号和公式引用。"""
import copy
from openpyxl.utils.cell import coordinate_to_tuple,get_column_letter
from .plan_layout import anchor_cell,merge_ranges
from .planbook import edit_cell
from .plan_sync import headers
from .inline_edit import linked_plan_orders


def clear_plan_cells(payload,index,points,orders):
    updated=copy.deepcopy(payload);sheet=updated['sheets'][index]
    columns,head=headers(sheet);fields={col:name for name,col in columns.items()}
    lookup={o['id']:copy.deepcopy(o) for o in orders};changed={};cleared=skipped=0
    for r,c in sorted({anchor_cell(sheet,r,c) for r,c in points}):
        if r<=head:raise ValueError('表头和标题不能批量清空，请单独编辑标题文字。')
        address=f'{get_column_letter(c)}{r}';entry=sheet['cells'].get(address,{})
        if 'f' in entry:skipped+=1;continue
        if entry.get('v') in (None,''):continue
        try:
            linked=linked_plan_orders(updated,sheet,r,c,fields.get(c,''),'',list(lookup.values()))
        except ValueError as exc:
            raise ValueError(f'{address} 无法清空：{exc} 如需移除整条计划，请使用“移除计划记录”。') from exc
        for order in linked:lookup[order['id']]=order;changed[order['id']]=order
        edit_cell(sheet,address,'');cleared+=1
    if cleared:
        for s in updated['sheets']:s['formulas_stale']=True
    return updated,list(changed.values()),cleared,skipped


def remove_plan_records(payload,index,rows,orders):
    updated=copy.deepcopy(payload);sheet=updated['sheets'][index];_,head=headers(sheet)
    rows=set(rows)
    if not rows:raise ValueError('请先选择要移除的计划记录。')
    if any(r<=head or r>sheet['rows'] for r in rows):raise ValueError('不能移除标题、表头或无效行，请只选择计划明细。')
    links=updated.get('order_links',[])
    removed=[l for l in links if l['sheet']==sheet['name'] and l['row'] in rows]
    updated['order_links']=[l for l in links if l not in removed]
    ranges=merge_ranges(sheet);cleared=0
    for address,entry in list(sheet['cells'].items()):
        r,c=coordinate_to_tuple(address)
        if r not in rows or 'f' in entry or entry.get('v') in (None,''):continue
        # 合并的父项还由其他明细使用时保留，不能把剩余子项的订单号清掉。
        if any(left<=c<=right and top<=r<=bottom and not set(range(top,bottom+1))<=rows for left,top,right,bottom in ranges):continue
        edit_cell(sheet,address,'');cleared+=1
    for s in updated['sheets']:s['formulas_stale']=True
    affected={l['order_id'] for l in removed}
    changed=[copy.deepcopy(o) for o in orders if o['id'] in affected]
    for order in changed:order['plan_sync_checked']=False
    return updated,changed,cleared,len(removed)
