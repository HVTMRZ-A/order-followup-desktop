import copy
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QCheckBox,QLabel,QPushButton,
 QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,QDialogButtonBox,QMessageBox)
from .plan_sync import TARGETS,DEFAULT_TARGETS,build_preview,apply_preview


class PlanJoinDialog(QDialog):
    def __init__(self,store,orders,parent):
        super().__init__(parent);self.store=store;self.orders=copy.deepcopy(orders);self.preview=[]
        self.setWindowTitle('确认加入计划总表');self.resize(1140,720)
        box=QVBoxLayout(self)
        hint=QLabel('核对目标表和数据后勾选确认。新增、补充空白及更新关联行分别列出；更新关联行默认不勾选，确认后才同步订单变化。无法处理的行保留待办。')
        hint.setWordWrap(True);box.addWidget(hint)
        self.targets={};default=set(n for o in orders for n in o.get('plan_targets',DEFAULT_TARGETS))
        for group in [TARGETS[:4],TARGETS[4:]]:
            row=QHBoxLayout()
            for name in group:
                check=QCheckBox(name);check.setChecked(name in default);check.toggled.connect(self.rebuild);self.targets[name]=check;row.addWidget(check)
            row.addStretch();box.addLayout(row)
        self.table=QTableWidget(0,7);self.table.setHorizontalHeaderLabels(['加入','订单号','型号','目标表','处理结果','关键数据','待处理内容'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive);self.table.horizontalHeader().setStretchLastSection(True)
        for column,width in enumerate([50,125,130,160,100,270]):self.table.setColumnWidth(column,width)
        box.addWidget(self.table,1)
        row=QHBoxLayout();edit=QPushButton('查看 / 补充所选行资料');edit.clicked.connect(self.edit_row);row.addWidget(edit)
        self.summary=QLabel();row.addWidget(self.summary,1);box.addLayout(row)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('确认加入并保存待办');buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);box.addWidget(buttons)
        self.rebuild()

    def selected_targets(self):return [n for n,c in self.targets.items() if c.isChecked()]

    def rebuild(self):
        if not hasattr(self,'table'):return
        choices={p['key']:self.table.item(r,0).checkState() for r,p in enumerate(self.preview) if p['state'] in ('新增','补充空白','待更新关联行') and self.table.item(r,0)}
        self.preview=build_preview(self.store.planbook(),self.orders,self.selected_targets());self.table.setRowCount(len(self.preview))
        for r,p in enumerate(self.preview):
            check=QTableWidgetItem();check.setFlags(Qt.ItemFlag.ItemIsUserCheckable|Qt.ItemFlag.ItemIsEnabled if p['state'] in ('新增','补充空白','待更新关联行') else Qt.ItemFlag.ItemIsEnabled)
            default=Qt.CheckState.Unchecked if p['state']=='待更新关联行' else Qt.CheckState.Checked
            check.setCheckState(choices.get(p['key'],default) if p['state'] in ('新增','补充空白','待更新关联行') else Qt.CheckState.Unchecked);self.table.setItem(r,0,check)
            keydata='；'.join(f'{k}：{v}' for k,v in p['values'].items() if v not in ('',None))
            notes=p['reason']+('；缺少'+ '、'.join(p['gaps']) if p['gaps'] else '')
            for c,value in enumerate([p['number'],p['model'],p['sheet'],p['state'],keydata,notes],1):
                item=QTableWidgetItem(value);item.setToolTip(value);self.table.setItem(r,c,item)
        self.table.setColumnWidth(5,240)
        self.summary.setText(f"可新增 {sum(p['state']=='新增' for p in self.preview)} 行，可补空白 {sum(p['state']=='补充空白' for p in self.preview)} 行，待确认更新 {sum(p['state']=='待更新关联行' for p in self.preview)} 行，已有 {sum(p['state']=='已存在' for p in self.preview)} 行，待处理 {sum(p['state'] in ('需核对','暂不能加入') for p in self.preview)} 行")

    def edit_row(self):
        r=self.table.currentRow()
        if r<0:return
        row=self.preview[r];dialog=QDialog(self);dialog.setWindowTitle('补充加入资料 · '+row['model']);dialog.resize(650,650);box=QVBoxLayout(dialog)
        box.addWidget(QLabel('这些内容用于加入计划表；不会改写原生产单。数量、日期等按实际填写。'))
        fields=list(row['values']);t=QTableWidget(len(fields),2);t.setHorizontalHeaderLabels(['字段','本次加入值'])
        for i,name in enumerate(fields):
            title=QTableWidgetItem(name);title.setFlags(Qt.ItemFlag.ItemIsEnabled);t.setItem(i,0,title);t.setItem(i,1,QTableWidgetItem(str(row['values'][name])))
        t.horizontalHeader().setStretchLastSection(True);box.addWidget(t)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存资料');buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);box.addWidget(buttons)
        if dialog.exec():
            values={name:t.item(i,1).text().strip() for i,name in enumerate(fields)}
            # 订单号和型号来自订单本身，避免补充资料时意外改绑。
            for key in ('订单号','产品型号','公司型号','型号'): 
                if key in row['values']:values[key]=row['values'][key]
            if row['sheet'] in ('最新','整体配件汇总','家用机订单'):
                for key in ('订单数量','数量','未完工数量','未发货','剩余数量'):
                    if key in row['values']:values[key]=row['values'][key]
            order=next(o for o in self.orders if o['id']==row['order_id'])
            order.setdefault('plan_overrides',{})[row['key']]=values;self.rebuild()

    def accept(self):
        if not self.selected_targets():QMessageBox.information(self,'请选择目标表','至少勾选一张适用的工作表。');return
        approved={p['key'] for r,p in enumerate(self.preview) if self.table.item(r,0).checkState()==Qt.CheckState.Checked}
        payload,orders,count=apply_preview(self.store.planbook(),self.orders,self.selected_targets(),approved)
        try:self.store.save_plan_join(payload,orders)
        except Exception as exc:QMessageBox.warning(self,'保存未完成',str(exc));return
        self.count=count;super().accept()
