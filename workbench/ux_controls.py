"""日常操作辅助：按需显示格式、选择关联订单、明确当前单元格。"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor,QPen
from PySide6.QtWidgets import (QPushButton,QDialog,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QListWidget,QListWidgetItem,QDialogButtonBox)


class FormatToggle(QPushButton):
    def __init__(self,bar,store,name,parent=None):
        super().__init__(parent);self.bar=bar;self.store=store;self.key='format_tools_open_'+name
        self.setCheckable(True);self.setToolTip('展开字体、颜色、对齐、行高及列宽设置；收起后显示更多记录')
        self.setChecked(store.get(self.key,'0')=='1');self.apply(self.isChecked(),False)
        self.toggled.connect(self.apply)
    def apply(self,opened,persist=True):
        self.bar.setVisible(opened);self.setText(('收起' if opened else '展开')+'格式设置')
        if persist:self.store.set(self.key,'1' if opened else '0')


def paint_current_cell(painter,option,index,table):
    if index==table.currentIndex():
        painter.save();painter.setPen(QPen(QColor('#245dce'),2));painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(option.rect.adjusted(1,1,-2,-2));painter.restore()


class OrderSelectionDialog(QDialog):
    def __init__(self,orders,selected_ids=(),parent=None):
        super().__init__(parent);self.setWindowTitle('选择关联订单');self.setObjectName('exportScopeDialog');self.resize(610,460);self.selected_ids=[]
        from .theme import export_scope_stylesheet
        self.setStyleSheet(export_scope_stylesheet());box=QVBoxLayout(self)
        box.addWidget(QLabel('勾选需要关联的订单；可按订单号、客户或经办人搜索。'))
        self.search=QLineEdit();self.search.setPlaceholderText('搜索订单号、客户、经办人');self.search.setClearButtonEnabled(True);box.addWidget(self.search)
        self.list=QListWidget();self.list.setObjectName('exportSheetList')
        for order in orders:
            text='  ｜  '.join(str(v) for v in (order['number'],order.get('customer') or order.get('customer_no',''),order.get('owner','')))
            item=QListWidgetItem(text);item.setData(Qt.ItemDataRole.UserRole,order['id']);item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable);item.setCheckState(Qt.CheckState.Checked if order['id'] in selected_ids else Qt.CheckState.Unchecked);self.list.addItem(item)
        box.addWidget(self.list,1);self.summary=QLabel();box.addWidget(self.summary)
        self.search.textChanged.connect(self.filter_items);self.list.itemChanged.connect(self.update_summary);self.update_summary()
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('确认关联');buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消');buttons.accepted.connect(self.confirm);buttons.rejected.connect(self.reject);box.addWidget(buttons)
    def filter_items(self,text):
        for i in range(self.list.count()):
            item=self.list.item(i);item.setHidden(text.strip().lower() not in item.text().lower())
    def update_summary(self,*args):
        count=sum(self.list.item(i).checkState()==Qt.CheckState.Checked for i in range(self.list.count()))
        self.summary.setText(f'已选择 {count} 个订单；隐藏的搜索结果仍保留勾选。')
    def confirm(self):
        self.selected_ids=[self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count()) if self.list.item(i).checkState()==Qt.CheckState.Checked];self.accept()
