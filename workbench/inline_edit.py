"""格内编辑的交互、类型转换和订单关联写回。"""
import copy
from datetime import datetime
from PySide6.QtCore import Qt,QObject,QEvent,QTimer
from PySide6.QtWidgets import QAbstractItemView,QLineEdit,QAbstractItemDelegate,QStyledItemDelegate
from .domain import number, fmt, validate_order
from .plan_layout import anchor_cell
from .production import DATE_COLUMNS, NUMBER_COLUMNS


def enable_cell_editing(table):
    table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked |
                          QAbstractItemView.EditTrigger.EditKeyPressed |
                          QAbstractItemView.EditTrigger.AnyKeyPressed)
    if not hasattr(table,'_spreadsheet_keys'):
        table._spreadsheet_keys=SpreadsheetKeys(table)
        table.installEventFilter(table._spreadsheet_keys)
    if type(table.itemDelegate()) is QStyledItemDelegate:
        table.setItemDelegate(SpreadsheetDelegate(table))


class SpreadsheetDelegate(QStyledItemDelegate):
    def createEditor(self,parent,option,index):
        editor=super().createEditor(parent,option,index)
        table=self.parent()
        if isinstance(editor,QLineEdit) and hasattr(table,'_spreadsheet_keys'):
            QTimer.singleShot(0,editor,lambda:editor.installEventFilter(table._spreadsheet_keys))
        return editor


class SpreadsheetKeys(QObject):
    """选择与编辑分开；确认输入后只移动选择，不自动编辑下一格。"""
    def __init__(self,table):
        super().__init__(table);self.table=table

    def eventFilter(self,obj,event):
        if event.type()!=QEvent.Type.KeyPress:return False
        table=self.table;key=event.key();mods=event.modifiers()
        if mods & (Qt.KeyboardModifier.ControlModifier|Qt.KeyboardModifier.AltModifier):return False
        editor=isinstance(obj,QLineEdit) and table.isAncestorOf(obj)
        if obj is not table and not editor:return False
        shift=bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if obj is table and key==Qt.Key.Key_F2:
            index=table.currentIndex()
            if index.isValid() and index.flags() & Qt.ItemFlag.ItemIsEditable:
                table.edit(index)
                for widget in table.findChildren(QLineEdit):
                    if widget.isVisible():widget.deselect();widget.setCursorPosition(len(widget.text()))
            return True
        if key in (Qt.Key.Key_Return,Qt.Key.Key_Enter,Qt.Key.Key_Tab,Qt.Key.Key_Backtab):
            if editor:
                delegate=table.itemDelegateForIndex(table.currentIndex())
                delegate.commitData.emit(obj)
                delegate.closeEditor.emit(obj,QAbstractItemDelegate.EndEditHint.NoHint)
            action=(QAbstractItemView.CursorAction.MoveUp if shift else QAbstractItemView.CursorAction.MoveDown) if key in (Qt.Key.Key_Return,Qt.Key.Key_Enter) else (QAbstractItemView.CursorAction.MovePrevious if shift or key==Qt.Key.Key_Backtab else QAbstractItemView.CursorAction.MoveNext)
            index=table.moveCursor(action,Qt.KeyboardModifier.NoModifier)
            if index.isValid():table.setCurrentIndex(index);table.scrollTo(index)
            table.setFocus()
            return True
        if obj is table and key==Qt.Key.Key_Delete:
            if hasattr(table,'clear_contents'):
                table.clear_contents();return True
            for item in table.selectedItems():
                if item.flags() & Qt.ItemFlag.ItemIsEditable:item.setText('')
            return True
        return False


def iso_date(text, optional=True):
    text = str(text).strip()
    if not text:
        if optional:
            return ''
        raise ValueError('日期不能为空，请填写 YYYY-MM-DD。')
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        for pattern in ('%Y/%m/%d', '%Y.%m.%d'):
            try:return datetime.strptime(text, pattern).date().isoformat()
            except ValueError:pass
    raise ValueError('日期格式不正确，请填写 YYYY-MM-DD，例如 2026-11-03。')


def plan_value(text, entry, field, sheet_name):
    if text == '':return ''
    if field in ('订单号','物料编码','物料代码','客户编号','客订编号','产品型号','公司型号','型号','计划序列号','计划序号'):
        return str(text)
    if entry.get('date') or (field in DATE_COLUMNS and not (sheet_name=='整体配件汇总' and field=='月份')) or field in ('下单时间','下请购单日期'):
        return iso_date(text)
    if isinstance(entry.get('v'), bool):
        if text.strip() in ('1','是','True','true'):return True
        if text.strip() in ('0','否','False','false'):return False
        raise ValueError('此单元格请填写“是”或“否”。')
    if isinstance(entry.get('v'), (int,float)) or field in NUMBER_COLUMNS or field in ('采购数量','毛重kg','总毛重kg'):
        value=number(text,field or '数量')
        return int(value) if value==int(value) else float(value)
    return text


def update_order_value(order, item_id, key, text, item_field=False):
    result=copy.deepcopy(order)
    target=next((i for i in result['items'] if i['id']==item_id),None) if item_field else result
    if target is None:raise ValueError('关联型号不存在，请刷新后重试。')
    if key=='quantity':value=fmt(number(text,'产品数量',positive=True))
    elif key in ('delivery_date','plan_delivery_date','analysis_at'):
        value=iso_date(text)
        if key=='analysis_at':target['analyzed']=bool(value)
    elif key=='received_at':
        value=iso_date(text,optional=False)+'T'+datetime.fromisoformat(order['received_at']).time().isoformat()
        if 'T' in str(text) or ' ' in str(text).strip():value=datetime.fromisoformat(str(text).strip()).isoformat(timespec='seconds')
    else:value=str(text).strip() if key!='requirement' else str(text)
    target[key]=value
    validate_order(result)
    return result


def plan_field_binding(field, sheet_name):
    order_fields={'订单号':'number','客户编号':'customer_no','客订编号':'customer_no',
                  '业务员':'owner','业务员/经办人':'owner','经办人':'owner',
                  '计划序列号':'plan_serial','计划序号':'plan_serial','接单日期':'received_at','受订日期':'received_at',
                  '生产单交期':'plan_delivery_date','计划完成日期':'plan_delivery_date','产品交期':'plan_delivery_date',
                  '客户交期':'delivery_date','订单属性':'attribute','运输方式':'transport'}
    item_fields={'产品型号':'model','公司型号':'model','型号':'model','物料编码':'material_code','物料代码':'material_code',
                 '产品要求':'requirement','规格型号':'requirement','规格':'requirement',
                 '类别':'category','产品大类':'category','订单数量':'quantity','分析时间':'analysis_at'}
    if field=='客户':return False,'customer_no' if sheet_name=='整体配件汇总' else 'customer'
    if field=='数量' and sheet_name=='家用机订单':return True,'quantity'
    if field in order_fields:return False,order_fields[field]
    if field in item_fields:return True,item_fields[field]
    return None


def linked_plan_orders(payload, sheet, row, column, field, value, orders):
    binding=plan_field_binding(field,sheet['name'])
    if binding is None:return []
    anchor=anchor_cell(sheet,row,column)
    links=[l for l in payload.get('order_links',[]) if l['sheet']==sheet['name'] and anchor_cell(sheet,l['row'],column)==anchor]
    item_field,key=binding
    identities={(l['order_id'],l['item_id']) for l in links}
    if item_field and len(identities)>1:
        raise ValueError('此合并格关联多个型号，请通过“打开关联订单”分别修改各型号。')
    changed={}
    for link in links:
        order=changed.get(link['order_id']) or next((o for o in orders if o['id']==link['order_id']),None)
        if order is None:raise ValueError('关联订单不存在，请刷新后重试。')
        changed[order['id']]=update_order_value(order,link['item_id'],key,str(value),item_field)
    return list(changed.values())
