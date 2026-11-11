"""会话内业务编辑撤销；按字段回放，保留不相关的新数据。"""
import copy
from dataclasses import dataclass
from PySide6.QtCore import QObject, Signal
from .domain import validate_order, stamp


def analysis_followup(order, records):
    records=copy.deepcopy(records);record=records.setdefault('分仓数据',{})
    identities=record.setdefault('order_ids',[])
    if order['id'] not in identities:identities.append(order['id'])
    text=order['number']+' 分析已确认，请在外部系统刷新分仓并检查异常'
    notes=record.get('notes','')
    if text not in notes:record['notes']=(notes+'；'+text).strip('；')
    record['state']='需要跟进';record['updated_at']=stamp()
    return records


class _Missing:
    def __deepcopy__(self, memo):return self
    def __eq__(self, other):return isinstance(other, _Missing)


MISSING = _Missing()
IGNORED = {'updated_at', 'plan_sync_checked', 'plan_pending', 'plan_overrides',
           'formulas_stale', 'display_styles', 'display_style_version', 'layout',
           'source_original_b64', 'source_history'}


@dataclass(frozen=True)
class Member:
    key: str
    value: str


def differences(before, after, path=()):
    if isinstance(before, dict) and isinstance(after, dict):
        for key in before.keys() | after.keys():
            if key not in IGNORED:
                yield from differences(before.get(key, MISSING), after.get(key, MISSING), path+(key,))
    elif isinstance(before, list) and isinstance(after, list) and before and after and all(isinstance(v, dict) for v in before+after):
        key = next((k for k in ('id', 'name') if all(k in v for v in before+after) and len({v[k] for v in before}) == len(before) and len({v[k] for v in after}) == len(after)), None)
        if key and {v[key] for v in before} == {v[key] for v in after}:
            lookup = {v[key]:v for v in after}
            for value in before:
                yield from differences(value, lookup[value[key]], path+(Member(key, value[key]),))
        elif before != after:yield path, copy.deepcopy(before), copy.deepcopy(after)
    elif before != after:
        yield path, copy.deepcopy(before), copy.deepcopy(after)


def child(value, part):
    if isinstance(part, Member):
        return next((v for v in value if v.get(part.key) == part.value), MISSING) if isinstance(value, list) else MISSING
    return value.get(part, MISSING) if isinstance(value, dict) else MISSING


def at(value, path):
    for part in path:value = child(value, part)
    return value


def assign(value, path, replacement):
    for part in path[:-1]:
        value = child(value, part)
        if value is MISSING:raise ValueError('关联记录已移除，无法撤销这次修改。')
    if replacement is MISSING:value.pop(path[-1], None)
    else:value[path[-1]] = copy.deepcopy(replacement)


class EditHistory(QObject):
    changed = Signal()

    def __init__(self, store, parent=None):
        super().__init__(parent);self.store=store;self.undo_stack=[];self.redo_stack=[]

    def capture(self, order_ids=(), plan=False, days=(),views=()):
        lookup={o['id']:o for o in self.store.orders()}
        result={'orders':{i:lookup.get(i, MISSING) for i in order_ids},
                'daily':{day:self.store.daily(day) for day in days},'views':{name:self.store.table_format(name) for name in views}}
        if plan:result['plan']=self.store.planbook()
        return result

    def record(self, label, before, review=True):
        after=self.capture(before['orders'], 'plan' in before, before['daily'],before.get('views',{}))
        patches=list(differences(before, after))
        if not patches:return
        command=dict(label=label, patches=patches, orders=tuple(before['orders']), days=tuple(before['daily']),views=tuple(before.get('views',{})),
                     recalculate=any(path[0]=='orders' or path[0]=='plan' and not any(p in ('format_edits','dimension_edits') for p in path if isinstance(p,str)) for path,_,_ in patches),
                     plan='plan' in before, revision=self.store.get('planbook_revision'),
                     data_revision=self.store.get('data_revision'), review=review)
        self.undo_stack.append(command);self.undo_stack=self.undo_stack[-100:];self.redo_stack.clear();self.changed.emit()

    def undo(self):return self._apply(False)
    def redo(self):return self._apply(True)

    def _apply(self, redo):
        source=self.redo_stack if redo else self.undo_stack
        target=self.undo_stack if redo else self.redo_stack
        if not source:return None
        command=source[-1]
        if command['data_revision'] != self.store.get('data_revision') or (command['plan'] and command['revision'] != self.store.get('planbook_revision')):
            raise ValueError('数据已重新导入或恢复，旧修改不能再撤销。')
        current=self.capture(command['orders'], command['plan'], command['days'],command['views'])
        for path, before, after in command['patches']:
            expected=before if redo else after
            if at(current, path) != expected:
                raise ValueError('相关内容已有新的修改或已移除，本次撤销未执行。')
        for path, before, after in command['patches']:assign(current, path, after if redo else before)
        orders=list(current['orders'].values())
        for order in orders:
            if order is MISSING:raise ValueError('订单已删除，无法撤销。请使用回收站。')
            validate_order(order)
            if command['review']:order['plan_sync_checked']=False
            order['updated_at']=stamp()
        plan=current.get('plan')
        if plan and command['recalculate']:
            for sheet in plan['sheets']:sheet['formulas_stale']=True
        label=('重做：' if redo else '撤销：')+command['label']
        self.store.apply_history(orders, plan, current['daily'], label,current.get('views'))
        source.pop();target.append(command);self.changed.emit()
        return label
