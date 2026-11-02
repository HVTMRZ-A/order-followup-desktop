"""订单删除确认及可恢复记录的界面。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
                              QPushButton, QTableWidget, QTableWidgetItem,
                              QAbstractItemView, QHeaderView, QMessageBox)


class DeleteOrderDialog(QDialog):
    def __init__(self, store, order, item_id=None, parent=None, staged=False):
        super().__init__(parent)
        self.setWindowTitle('删除型号' if item_id else '删除整单')
        self.resize(620, 400)
        box = QVBoxLayout(self)
        items = [i for i in order['items'] if item_id is None or i['id'] == item_id]
        identities = {i['id'] for i in items}
        materials = [m for m in order.get('materials', []) if m['item_id'] in identities]
        links = [l for l in (store.planbook() or {}).get('order_links', [])
                 if l['order_id'] == order['id'] and l['item_id'] in identities]
        title = f"订单 {order['number']}" + (f" / {items[0]['model']}" if item_id else '（整单）')
        heading = QLabel(title)
        heading.setWordWrap(True)
        heading.setObjectName('dialogTitle')
        box.addWidget(heading)
        text = f'将移除 {len(items)} 个型号和 {len(materials)} 项关联包材，并停止相应订单待办。'
        text += f'\n有 {len(links)} 条计划行关联将解除。'
        if not item_id:
            text += '\n每日跟进保留历史说明，解除该订单的关联；其他订单不受影响。'
        if staged:
            text += '\n点击订单详情的“保存”后生效；取消订单编辑则不删除。'
        else:
            text += '\n确认后移入回收站，删除前自动备份，可恢复订单或型号及包材。'
        info = QLabel(text)
        info.setWordWrap(True)
        box.addWidget(info)
        self.clear_plan = QCheckBox('同时清空计划总表中关联行的输入值')
        self.clear_plan.setEnabled(bool(links))
        box.addWidget(self.clear_plan)
        note = QLabel('默认保留计划表历史内容。勾选后保留行号、格式和公式；未关联的历史行及与其他订单共用的行保留。\n恢复订单后，计划表及每日关联需重新确认；自动备份保留删除前的完整记录。')
        note.setWordWrap(True)
        box.addWidget(note)
        box.addStretch()
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton('取消')
        cancel.clicked.connect(self.reject)
        cancel.setDefault(True)
        row.addWidget(cancel)
        confirm = QPushButton('确认移除，保存后生效' if staged else '确认删除并移入回收站')
        confirm.setObjectName('danger')
        confirm.clicked.connect(self.accept)
        confirm.setAutoDefault(False)
        row.addWidget(confirm)
        box.addLayout(row)


class OrderTrashDialog(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle('订单回收站')
        self.resize(880, 520)
        box = QVBoxLayout(self)
        info = QLabel('恢复订单或型号及其包材记录，不覆盖现有数据。计划表和每日关联恢复后需重新确认。若所属整单也已删除，请先恢复整单。')
        info.setWordWrap(True)
        box.addWidget(info)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(['删除时间', '类型', '订单号', '型号', '包材项数', '计划行处理'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        box.addWidget(self.table, 1)
        row = QHBoxLayout()
        restore = QPushButton('恢复所选记录')
        restore.clicked.connect(self.restore_selected)
        row.addWidget(restore)
        row.addStretch()
        close = QPushButton('关闭')
        close.clicked.connect(self.accept)
        row.addWidget(close)
        box.addLayout(row)
        self.reload()

    def reload(self):
        records = self.main.store.trash()
        self.table.setRowCount(len(records))
        for row, record in enumerate(records):
            order = record['order']
            items = [i for i in order['items'] if record['kind'] == 'order' or i['id'] == record['item_id']]
            ids = {i['id'] for i in items}
            values = [record['deleted_at'].replace('T', ' '), '整单' if record['kind'] == 'order' else '型号',
                      order['number'], '、'.join(i['model'] for i in items),
                      str(sum(m['item_id'] in ids for m in order.get('materials', []))),
                      '清空输入值' if record['clear_plan_rows'] else '保留历史内容']
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.ItemDataRole.UserRole, record['id'])
                cell.setToolTip(value)
                self.table.setItem(row, col, cell)

    def restore_selected(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, '选择记录', '请先选择需要恢复的订单或型号。')
            return
        identity = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        try:
            order = self.main.store.restore_deleted(identity)
        except Exception as exc:
            QMessageBox.warning(self, '暂不能恢复', str(exc))
            return
        self.main.load_daily()
        self.main.planbook_page.reload()
        self.main.refresh()
        self.reload()
        self.main.status.showMessage(f"已恢复 {order['number']}，请在订单管理中确认加入计划总表。", 8000)
