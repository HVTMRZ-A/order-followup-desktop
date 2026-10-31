from pathlib import Path
import copy
from PySide6.QtCore import Qt,QThread,Signal
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTabWidget,
 QTableWidget,QTableWidgetItem,QAbstractItemView,QFileDialog,QMessageBox,QDialog,QTextEdit,QDialogButtonBox,QLineEdit)
from openpyxl.utils.cell import get_column_letter
from .planbook import EXPECTED_SHEETS,read_planbook,export_planbook,displayed,edit_cell


class Job(QThread):
    ready=Signal(object);failed=Signal(str)
    def __init__(self,fn,parent):super().__init__(parent);self.fn=fn
    def run(self):
        try:self.ready.emit(self.fn())
        except Exception as exc:self.failed.emit(str(exc))


class PlanBookWidget(QWidget):
    def __init__(self,store,main):
        super().__init__(main);self.store=store;self.main=main;self.payload=None;self.tables=[]
        self.setAcceptDrops(True)
        box=QVBoxLayout(self);box.setContentsMargins(24,24,24,20);box.setSpacing(12)
        title=QLabel('计划总表');title.setObjectName('title');box.addWidget(title)
        self.info=QLabel('导入完整计划总表后，显示全部可见工作表及历史记录。隐藏表不导入、不导出。');self.info.setWordWrap(True);box.addWidget(self.info)
        actions=QHBoxLayout()
        self.import_button=QPushButton('导入计划总表');self.import_button.clicked.connect(self.import_book);actions.addWidget(self.import_button)
        self.export_button=QPushButton('导出完整总表');self.export_button.clicked.connect(self.export_book);actions.addWidget(self.export_button)
        if hasattr(main,'import_orders'):
            orders=QPushButton('生产单导入');orders.clicked.connect(main.import_orders);actions.addWidget(orders)
            new=QPushButton('新订单');new.clicked.connect(lambda:main.edit_order());actions.addWidget(new)
            follow=QPushButton('订单跟进');follow.clicked.connect(main.open_order_actions);actions.addWidget(follow)
        box.addLayout(actions)
        actions=QHBoxLayout()
        if hasattr(main,'import_orders'):
            join=QPushButton('订单加入总表 / 处理待办');join.clicked.connect(lambda:main.confirm_plan_join());actions.addWidget(join)
            related=QPushButton('打开关联订单');related.clicked.connect(self.open_related_order);actions.addWidget(related)
        edit=QPushButton('编辑所选单元格');edit.clicked.connect(self.edit_selected);actions.addWidget(edit)
        add=QPushButton('新增一行');add.clicked.connect(self.add_row);actions.addWidget(add);actions.addStretch();box.addLayout(actions)
        self.search=QLineEdit();self.search.setAcceptDrops(False);self.search.setPlaceholderText('在当前工作表查找订单、型号、物料或备注');self.search.textChanged.connect(self.filter_rows);box.addWidget(self.search)
        self.tabs=QTabWidget();self.tabs.setUsesScrollButtons(True);self.tabs.currentChanged.connect(self.filter_rows);box.addWidget(self.tabs,1)
        self.status=QLabel('');self.status.setWordWrap(True);box.addWidget(self.status)
        note=QLabel('输入格修改后自动保存到本机。原表公式格仅查看；相关公式在输入修改后显示公式，导出后请用 Excel 重新计算。');note.setWordWrap(True);box.addWidget(note)
        self.reload()

    def reload(self):
        self.payload=self.store.planbook();self.tabs.clear();self.tables=[]
        for sheet in (self.payload['sheets'] if self.payload else [dict(name=n,rows=0,cols=0,cells={}) for n in EXPECTED_SHEETS]):
            table=QTableWidget();table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);table.setAlternatingRowColors(True)
            table.setAcceptDrops(False);table.viewport().setAcceptDrops(False)
            table.setRowCount(sheet['rows']);table.setColumnCount(sheet['cols'])
            table.setHorizontalHeaderLabels([get_column_letter(c+1) for c in range(sheet['cols'])]);table.verticalHeader().setDefaultSectionSize(32)
            table.horizontalHeader().setDefaultSectionSize(130)
            for address,entry in sheet['cells'].items():
                from openpyxl.utils.cell import coordinate_to_tuple
                r,c=coordinate_to_tuple(address);item=QTableWidgetItem(displayed(sheet,address));item.setToolTip(entry.get('f') or str(entry.get('v') or ''));table.setItem(r-1,c-1,item)
            for link in (self.payload or {}).get('order_links',[]):
                if link['sheet']!=sheet['name'] or link['row']>table.rowCount():continue
                cell=table.item(link['row']-1,0)
                if cell is None:cell=QTableWidgetItem('');table.setItem(link['row']-1,0,cell)
                cell.setData(Qt.ItemDataRole.UserRole,link);cell.setToolTip('关联订单：双击打开详情')
            table.cellDoubleClicked.connect(lambda r,c:self.open_related_order() if self.selected_link() else self.edit_selected());self.tables.append(table);self.tabs.addTab(table,sheet['name'])
        if self.payload:self.info.setText(f"{self.payload['name']} · {len(self.payload['sheets'])} 张可见工作表 · 原文件未改动")
        self.export_button.setEnabled(bool(self.payload));self.filter_rows()

    def selected_link(self):
        if self.tabs.currentIndex()<0:return None
        table=self.tables[self.tabs.currentIndex()];r=table.currentRow()
        return table.item(r,0).data(Qt.ItemDataRole.UserRole) if r>=0 and table.item(r,0) else None

    def open_related_order(self):
        link=self.selected_link()
        order=next((o for o in self.store.orders() if link and o['id']==link['order_id']),None)
        if order:self.main.edit_order(order)
        else:QMessageBox.information(self,'尚未关联','此历史行尚未关联工作台订单；可在订单管理中导入原单，再确认加入 / 关联计划总表。')

    def run_job(self,fn,callback):
        self.import_button.setEnabled(False);self.export_button.setEnabled(False)
        job=Job(fn,self);self.main.workers.append(job)
        job.ready.connect(callback);job.failed.connect(lambda message:QMessageBox.warning(self,'操作未完成',message))
        def finished():
            self.main.workers.remove(job);self.import_button.setEnabled(True);self.export_button.setEnabled(bool(self.payload));job.deleteLater()
        job.finished.connect(finished);job.start()

    def import_book(self):
        path,_=QFileDialog.getOpenFileName(self,'选择计划总表','','Excel (*.xlsx *.xlsm)')
        if not path:return
        self.import_path(path)

    def import_path(self,path):
        if self.payload and QMessageBox.question(self,'替换计划总表','导入会替换当前计划总表及其中修改，替换前自动备份本机数据库。继续？')!=QMessageBox.StandardButton.Yes:return
        self.status.setText('正在读取全部可见工作表，请稍候……')
        self.run_job(lambda:read_planbook(path),self.import_ready)

    def dragEnterEvent(self,event):self.main.dragEnterEvent(event)
    def dragMoveEvent(self,event):self.main.dragMoveEvent(event)
    def dragLeaveEvent(self,event):self.main.dragLeaveEvent(event)
    def dropEvent(self,event):self.main.dropEvent(event)

    def import_ready(self,result):
        payload,source=result
        summary='\n'.join(f"{s['name']}：{s['rows']} 行 × {s['cols']} 列" for s in payload['sheets'])
        if QMessageBox.question(self,'导入预览',summary+'\n\n隐藏表已排除。确认导入这些工作表？')!=QMessageBox.StandardButton.Yes:self.status.setText('已取消，现有数据未改变。');return
        self.store.backup();self.store.save_planbook(payload,source);self.reload();self.status.setText('导入完成。双击输入格可编辑；也可新增行。')
        if hasattr(self.main,'confirm_plan_join') and self.store.orders():
            self.main.refresh();self.main.confirm_plan_join()

    def export_book(self):
        if not self.payload:return
        suffix='.xlsm' if self.payload['name'].lower().endswith('.xlsm') else '.xlsx'
        path,_=QFileDialog.getSaveFileName(self,'另存完整计划总表','计划总表_工作台'+suffix,'Excel (*'+suffix+')')
        if not path:return
        payload=copy.deepcopy(self.payload);source=self.store.planbook_source();self.status.setText('正在导出全部可见工作表……')
        self.run_job(lambda:export_planbook(path,payload,source),lambda _:self.status.setText('已导出：'+path+'；请用 Excel 打开重新计算公式。'))

    def edit_selected(self):
        if not self.payload:return
        index=self.tabs.currentIndex();table=self.tables[index];r,c=table.currentRow(),table.currentColumn()
        if r<0 or c<0:return
        sheet=self.payload['sheets'][index];address=f'{get_column_letter(c+1)}{r+1}';entry=sheet['cells'].get(address,{})
        link=self.selected_link()
        if link:
            from .plan_sync import headers,MASTER_FIELDS,normalized
            columns,_=headers(sheet);field=next((n for n,col in columns.items() if col==c+1),'')
            if field in {normalized(n) for n in MASTER_FIELDS | ({'数量'} if sheet['name']=='家用机订单' else set())}:
                QMessageBox.information(self,'编辑关联订单','此字段来自订单管理。请修改关联订单，再在预览中确认更新计划行，避免两处数据不一致。')
                self.open_related_order();return
        if 'f' in entry:QMessageBox.information(self,'原表公式',entry.get('f') or '此格为原表共享公式。请修改相应输入格，导出后由 Excel 重算。');return
        dialog=QDialog(self);dialog.setWindowTitle(sheet['name']+' · '+address);dialog.resize(520,280);box=QVBoxLayout(dialog)
        editor=QTextEdit(str(entry.get('v') if entry.get('v') is not None else ''));box.addWidget(editor)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);box.addWidget(buttons)
        if not dialog.exec():return
        value=editor.toPlainText()
        # 已有数字格保留数值类型；其它格保持文本，保护订单号和料号的前导零。
        if isinstance(entry.get('v'),(int,float)) and not isinstance(entry.get('v'),bool) and value:
            try:value=float(value);value=int(value) if value.is_integer() else value
            except ValueError:pass
        edit_cell(sheet,address,value)
        for s in self.payload['sheets']:s['formulas_stale']=True
        self.store.save_planbook(self.payload);self.reload();self.tabs.setCurrentIndex(index);self.status.setText(f'已保存 {sheet["name"]}!{address}。公式结果待 Excel 重算。')

    def add_row(self):
        if not self.payload:return
        index=self.tabs.currentIndex();sheet=self.payload['sheets'][index];sheet['rows']+=1
        self.store.save_planbook(self.payload);self.reload();self.tabs.setCurrentIndex(index)
        table=self.tables[index];table.setCurrentCell(sheet['rows']-1,0);table.scrollToBottom();self.status.setText('已新增空行；双击单元格填写。')

    def filter_rows(self,*args):
        index=self.tabs.currentIndex()
        if index<0 or index>=len(self.tables):return
        table=self.tables[index];text=self.search.text().strip().lower()
        for r in range(table.rowCount()):
            visible=not text or any(text in table.item(r,c).text().lower() for c in range(table.columnCount()) if table.item(r,c))
            table.setRowHidden(r,not visible)
        self.status.setText(f'当前工作表：{table.rowCount()} 行、{table.columnCount()} 列')
