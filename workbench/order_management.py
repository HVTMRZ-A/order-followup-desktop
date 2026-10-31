"""导入原单的完整明细与原件；计划表加入仍单独预览确认。"""
import copy,base64,hashlib
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QPushButton,QLineEdit,QTableWidget,QTableWidgetItem,
 QHeaderView,QAbstractItemView,QLabel,QFileDialog,QMessageBox)

HEADERS=['订单号','公司型号','物料编码','产品数量','产品要求','单位','客户编号','客户','经办人','接单日期','交期',
         '订单属性','运输方式','产品大类','客户型号','原单包材','原单BOM状态','原单文件','跟进状态']


def merge_source(existing,incoming):
    result=copy.deepcopy(existing);changes=[];conflicts=[]
    for key in ('customer_no','customer','owner','received_at','delivery_date','plan_delivery_date','transport','attribute','notes'):
        value=incoming.get(key)
        if value and not result.get(key):result[key]=value;changes.append(key)
        elif value and result.get(key)!=value:conflicts.append(key)
    for new in incoming['items']:
        old=next((i for i in result['items'] if i['model']==new['model']),None)
        if old is None:conflicts.append('未匹配型号：'+new['model']);continue
        for key in ('material_code','category','customer_model','requirement','unit','packaging_name','bom_status'):
            value=new.get(key)
            if value and not old.get(key):old[key]=value;changes.append(new['model']+'：'+key)
            elif value and old.get(key)!=value:conflicts.append(new['model']+'：'+key)
        old.setdefault('source_columns',{}).update(new.get('source_columns',{}))
    if existing.get('source_original_b64') and existing.get('source_sha256')!=incoming.get('source_sha256'):
        result.setdefault('source_history',[]).append({k:existing.get(k) for k in ('source_original_b64','source_sha256','source_file')})
    for key in ('source_original_b64','source_sha256','source_file','source_sheet','source_titles'):
        if key in incoming:result[key]=incoming[key]
    return result,changes,conflicts


class OrderManagementWidget(QWidget):
    def __init__(self,main):
        super().__init__(main);self.main=main;self.setAcceptDrops(True);box=QVBoxLayout(self);box.setContentsMargins(26,24,26,20);box.setSpacing(14)
        title=QLabel('订单管理');title.setObjectName('title');box.addWidget(title)
        box.addWidget(QLabel('导入的订单先保存在这里，保留物料编码、规格要求及原始单据；确认后再加入计划总表。'))
        row=QHBoxLayout()
        for text,fn in [('导入订单',main.import_orders),('新订单',lambda:main.edit_order()),('导入模板',main.template),
                        ('加入计划总表',self.join_selected),('查看 / 导出原单',self.export_original),('补充原单资料',self.supplement)]:
            b=QPushButton(text);b.clicked.connect(fn);row.addWidget(b)
        daily=QPushButton('关联每日跟进');daily.clicked.connect(self.daily_for_selected);row.addWidget(daily)
        box.addLayout(row);self.search=QLineEdit();self.search.setAcceptDrops(False);self.search.setPlaceholderText('搜索订单号、客户、型号、物料编码、产品要求……');self.search.textChanged.connect(self.refresh);box.addWidget(self.search)
        self.table=QTableWidget(0,len(HEADERS));self.table.setHorizontalHeaderLabels(HEADERS);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.setAlternatingRowColors(True);self.table.setAcceptDrops(False);self.table.viewport().setAcceptDrops(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for c in range(len(HEADERS)):self.table.setColumnWidth(c,125)
        self.table.setColumnWidth(2,190);self.table.setColumnWidth(3,90);self.table.setColumnWidth(4,360);self.table.setColumnWidth(5,60)
        self.table.cellDoubleClicked.connect(lambda r,c:self.open_selected());box.addWidget(self.table,1)
        self.status=QLabel();box.addWidget(self.status);b=QPushButton('打开所选订单详情');b.clicked.connect(self.open_selected);box.addWidget(b)
        self.relations=QLabel('选择订单可查看合同、BOM、分析、计划行及关联异常。');self.relations.setWordWrap(True);box.addWidget(self.relations)
        self.table.itemSelectionChanged.connect(self.show_relations)

    def selected(self):
        r=self.table.currentRow()
        if r<0:return None
        identity=self.table.item(r,0).data(Qt.ItemDataRole.UserRole)
        return next((o for o in self.main.store.orders() if o['id']==identity),None)

    def dragEnterEvent(self,event):self.main.dragEnterEvent(event)
    def dragMoveEvent(self,event):self.main.dragMoveEvent(event)
    def dragLeaveEvent(self,event):self.main.dragLeaveEvent(event)
    def dropEvent(self,event):self.main.dropEvent(event)

    def refresh(self,*args):
        selected=self.selected();selected_id=selected['id'] if selected else None
        self.table.setRowCount(0);text=self.search.text().strip().lower();orders=self.main.store.orders()
        for order in orders:
            for item in order['items']:
                values=[order['number'],item['model'],item.get('material_code',''),item['quantity'],item.get('requirement',''),item.get('unit',''),
                    order.get('customer_no',''),order.get('customer',''),order.get('owner',''),order.get('received_at',''),
                    order.get('plan_delivery_date') or order.get('delivery_date',''),order.get('attribute',''),order.get('transport',''),item.get('category',''),item.get('customer_model',''),
                    item.get('packaging_name',''),item.get('bom_status',''),order.get('source_file',''),'完成' if item.get('completed') else '进行中']
                if text and text not in ' '.join(map(str,values)).lower():continue
                r=self.table.rowCount();self.table.insertRow(r)
                for c,v in enumerate(values):
                    cell=QTableWidgetItem(str(v));cell.setToolTip(str(v));cell.setData(Qt.ItemDataRole.UserRole,order['id']);self.table.setItem(r,c,cell)
        self.status.setText(f'已登记 {len(orders)} 个订单，当前显示 {self.table.rowCount()} 条型号明细。双击查看订单详情。')
        for r in range(self.table.rowCount()):
            if self.table.item(r,0).data(Qt.ItemDataRole.UserRole)==selected_id:self.table.setCurrentCell(r,0);break

    def open_selected(self):
        o=self.selected()
        if o:self.main.edit_order(o)

    def join_selected(self):
        o=self.selected()
        if o:self.main.confirm_plan_join([o])
        else:QMessageBox.information(self,'选择订单','请先选择一个订单。')

    def daily_for_selected(self):
        order=self.selected()
        if order:self.main.follow_order_daily(order)

    def show_relations(self):
        order=self.selected()
        if not order:self.relations.setText('选择订单可查看合同、BOM、分析、计划行及关联异常。');return
        plan=self.main.store.planbook() or {};links=[l for l in plan.get('order_links',[]) if l['order_id']==order['id']]
        pending=sum(record.get('state')=='需要跟进' and order['id'] in record.get('order_ids',[]) for _,records in self.main.store.daily_all() for record in records.values())
        n=len(order['items']);bom=sum(bool(i.get('bom')) for i in order['items']);analysis=sum(bool(i.get('analyzed')) for i in order['items'])
        self.relations.setText(f"{order['number']}：合同{'已确认' if order.get('contract') else '待确认'}；BOM {bom}/{n}；分析 {analysis}/{n}；关联计划 {len(links)} 行；包材 {len(order.get('materials',[]))} 项；关联未解决跟进 {pending} 项")

    def export_original(self):
        o=self.selected()
        if not o:return
        if not o.get('source_original_b64'):QMessageBox.information(self,'尚未保存原件','旧记录没有原件副本。可用“补充原单资料”选择原文件，已读取的物料编码等仍可在列表查看。');return
        name=o.get('source_file','订单原件.xlsx');path,_=QFileDialog.getSaveFileName(self,'保存原始导入文件',name,'原始文件 (*'+Path(name).suffix+')')
        if path:Path(path).write_bytes(base64.b64decode(o['source_original_b64']));QMessageBox.information(self,'原件已保存','原始文件已原样导出，可打开核对全部内容。')

    def supplement(self):
        existing=self.selected()
        if not existing:return
        path,_=QFileDialog.getOpenFileName(self,'选择该订单的原始单据','','订单文件 (*.xlsx *.xlsm *.csv)')
        if not path:return
        from .importer import read_any
        try:
            incoming=next((o for o in read_any(path) if o['number']==existing['number']),None)
            if incoming is None:raise ValueError('原单订单号与所选订单不一致')
            merged,changes,conflicts=merge_source(existing,incoming)
        except Exception as exc:QMessageBox.warning(self,'读取未完成',str(exc));return
        message='将补充空白字段并保留原件：\n'+'\n'.join(changes[:20])
        if conflicts:message+='\n以下已有字段不覆盖，请核对原单：\n'+'\n'.join(conflicts[:20])
        if QMessageBox.question(self,'确认补充资料',message)!=QMessageBox.StandardButton.Yes:return
        self.main.store.save_order(merged,'补充原单资料（保留已有确认）');self.main.refresh()
