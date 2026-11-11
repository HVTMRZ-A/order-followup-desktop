from pathlib import Path
import copy
from PySide6.QtCore import Qt,QThread,Signal,QTimer,QSignalBlocker
from PySide6.QtGui import QFont,QColor,QPen,QPalette,QAction,QKeySequence
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTabWidget,
 QTableWidget,QTableWidgetItem,QAbstractItemView,QFileDialog,QMessageBox,QDialog,QTextEdit,QDialogButtonBox,QLineEdit,QCheckBox,QStyle,QStyleOptionViewItem,QStyleFactory,QMenu,QAbstractItemDelegate)
from openpyxl.utils.cell import get_column_letter
from .planbook import EXPECTED_SHEETS,read_planbook,export_planbook,displayed,edit_cell
from .plan_layout import ensure_layout,layout_ready,merge_ranges,anchor_cell,order_groups
from .inline_edit import enable_cell_editing,plan_value,linked_plan_orders,SpreadsheetDelegate
from .cell_format import effective_style,selected_cells
from .format_controls import FormatBar,PlanFormatting,HeaderSizing,apply_item_style,apply_dimensions,EXPLICIT_BOLD,WRAP_ROLE
from .ux_controls import FormatToggle,paint_current_cell


class Job(QThread):
    ready=Signal(object);failed=Signal(str)
    def __init__(self,fn,parent):super().__init__(parent);self.fn=fn
    def run(self):
        try:self.ready.emit(self.fn())
        except Exception as exc:self.failed.emit(str(exc))


class OrderHierarchyDelegate(SpreadsheetDelegate):
    def __init__(self,table):
        super().__init__(table);self.table=table
        # 应用的白底样式会覆盖 Qt 的单元格底色。格子使用原生样式绘制，
        # 直接遵守模型颜色；选中仍使用工作台的浅蓝高亮。
        self.cell_style=QStyleFactory.create('Fusion');self.cell_style.setParent(self)
        self.rebuild()

    def rebuild(self):
        self.by_row={r:g for g in self.table.order_groups for r in range(g['start'],g['end']+1)}
        columns=self.table.order_columns
        self.number_col=columns.get('订单号',0)-1
        self.model_col=next((columns[n]-1 for n in ('产品型号','公司型号','型号','规格型号') if n in columns),-1)

    def initStyleOption(self,option,index):
        super().initStyleOption(option,index)
        wrap=index.data(WRAP_ROLE)
        if wrap is not None:
            if wrap:option.features |= QStyleOptionViewItem.ViewItemFeature.WrapText
            else:option.features &= ~QStyleOptionViewItem.ViewItemFeature.WrapText
        if index.row()+1 in self.by_row:
            if index.column()==self.model_col and option.text:
                group=self.by_row[index.row()+1];option.text=('└─ ' if index.row()+1==group['end'] else '├─ ')+option.text
            if index.column()==self.number_col and index.data(EXPLICIT_BOLD) is None:option.font.setBold(True)

    def paint(self,painter,option,index):
        option=QStyleOptionViewItem(option);option.state &= ~QStyle.StateFlag.State_MouseOver
        self.initStyleOption(option,index)
        option.palette.setColor(QPalette.ColorRole.Base,QColor('#ffffff'))
        option.palette.setColor(QPalette.ColorRole.Highlight,QColor('#dce9ff'))
        option.palette.setColor(QPalette.ColorRole.HighlightedText,QColor('#16202f'))
        self.cell_style.drawControl(QStyle.ControlElement.CE_ItemViewItem,option,painter,self.table)
        group=self.by_row.get(index.row()+1)
        if group:
            painter.save();painter.setPen(QPen(QColor('#b9c5d5'),1))
            if index.row()+1==group['start']:painter.drawLine(option.rect.topLeft(),option.rect.topRight())
            if index.row()+1==group['end']:painter.drawLine(option.rect.bottomLeft(),option.rect.bottomRight())
            painter.restore()
        paint_current_cell(painter,option,index,self.table)


class PlanBookWidget(QWidget):
    def __init__(self,store,main):
        super().__init__(main);self.store=store;self.main=main;self.payload=None;self.tables=[]
        self.setAcceptDrops(True)
        box=QVBoxLayout(self);box.setContentsMargins(24,24,24,20);box.setSpacing(12)
        title=QLabel('计划总表');title.setObjectName('title');box.addWidget(title)
        self.info=QLabel('导入完整计划总表后，显示全部可见工作表及历史记录。隐藏表不导入、不导出。');self.info.setWordWrap(True);box.addWidget(self.info)
        actions=QHBoxLayout()
        self.import_button=QPushButton('导入计划总表');self.import_button.clicked.connect(self.import_book);actions.addWidget(self.import_button)
        self.save_button=QPushButton('保存到本机');self.save_button.setToolTip('Ctrl+S；保存工作台内的数据，生成 Excel 请用“导出”');self.save_button.clicked.connect(self.save_current);actions.addWidget(self.save_button)
        self.export_button=QPushButton('导出');self.export_button.setToolTip('可导出全部、当前或勾选的工作表');self.export_button.clicked.connect(self.export_book);actions.addWidget(self.export_button)
        self.save_action=QAction(self);self.save_action.setShortcut(QKeySequence('Ctrl+S'));self.save_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut);self.save_action.triggered.connect(self.save_current);self.addAction(self.save_action)
        if hasattr(main,'import_orders'):
            orders=QPushButton('生产单导入');orders.clicked.connect(main.import_orders);actions.addWidget(orders)
            new=QPushButton('新订单');new.clicked.connect(lambda:main.edit_order());actions.addWidget(new)
            follow=QPushButton('订单跟进');follow.clicked.connect(main.open_order_actions);actions.addWidget(follow)
        box.addLayout(actions)
        actions=QHBoxLayout()
        if hasattr(main,'import_orders'):
            join=QPushButton('订单加入总表 / 处理待办');join.clicked.connect(lambda:main.confirm_plan_join());actions.addWidget(join)
            related=QPushButton('打开关联订单');related.clicked.connect(self.open_related_order);actions.addWidget(related)
        edit=QPushButton('详细编辑（长文本）');edit.clicked.connect(self.edit_selected);actions.addWidget(edit)
        add=QPushButton('新增一行');add.clicked.connect(self.add_row);actions.addWidget(add)
        self.show_colors=QCheckBox('显示原表颜色');self.show_colors.setChecked(self.store.get('plan_show_colors','1')=='1')
        self.show_colors.toggled.connect(self.toggle_colors);actions.addWidget(self.show_colors);actions.addStretch();box.addLayout(actions)
        search_row=QHBoxLayout()
        self.search=QLineEdit();self.search.setAcceptDrops(False);self.search.setClearButtonEnabled(True);self.search.setPlaceholderText('在当前工作表查找订单、型号、物料或备注');self.search.textChanged.connect(self.filter_rows);search_row.addWidget(self.search,1)
        self.formatter=PlanFormatting(self);self.format_bar=FormatBar(self.formatter,self);self.format_toggle=FormatToggle(self.format_bar,self.store,'plan',self);search_row.addWidget(self.format_toggle);box.addLayout(search_row);box.addWidget(self.format_bar)
        self.relationship=QLabel('选择明细可查看所属订单及同组明细范围。');self.relationship.setWordWrap(True);self.relationship.setTextFormat(Qt.TextFormat.PlainText);box.addWidget(self.relationship)
        value_row=QHBoxLayout();self.cell_address=QLabel('所选格');value_row.addWidget(self.cell_address)
        self.cell_value=QLineEdit();self.cell_value.setReadOnly(True);self.cell_value.setPlaceholderText('选中格的完整内容在这里查看、复制；双击表格或 F2 修改');value_row.addWidget(self.cell_value,1);box.addLayout(value_row)
        operations=QHBoxLayout()
        self.clear_button=QPushButton('清空所选内容');self.clear_button.setToolTip('Delete；只清空输入值，保留公式和格式');self.clear_button.clicked.connect(lambda:self.clear_selected());operations.addWidget(self.clear_button)
        self.remove_button=QPushButton('移除计划记录');self.remove_button.setObjectName('danger');self.remove_button.setToolTip('移除所选行的计划数据与关联；保留空行、公式及原订单');self.remove_button.clicked.connect(self.remove_selected_records);operations.addWidget(self.remove_button)
        self.saved_info=QLabel('修改后自动保存到本机；生成 Excel 文件请使用“导出”。');self.saved_info.setWordWrap(True);operations.addWidget(self.saved_info,1);box.addLayout(operations)
        self.tabs=QTabWidget();self.tabs.setUsesScrollButtons(True);self.tabs.currentChanged.connect(self.filter_rows);box.addWidget(self.tabs,1)
        self.status=QLabel('');self.status.setWordWrap(True);box.addWidget(self.status)
        note=QLabel('单击选择；双击 / F2 编辑，直接键入替换。Enter 保存，Esc 取消。Ctrl+S 保存到本机，Ctrl+Z 撤销。');note.setWordWrap(True);box.addWidget(note)
        self.reload()

    def reload(self):
        previous=self.tabs.currentIndex();positions=[(t.currentRow(),t.currentColumn(),t.verticalScrollBar().value(),t.horizontalScrollBar().value(),t.selectedRanges()) for t in self.tables]
        self.payload=self.store.planbook()
        if self.payload and not layout_ready(self.payload):
            ensure_layout(self.payload,self.store.planbook_source());self.store.save_planbook(self.payload)
        old_tables=self.tables;self.tabs.clear();self.tables=[]
        for old in old_tables:old.deleteLater()
        for sheet in (self.payload['sheets'] if self.payload else [dict(name=n,rows=0,cols=0,cells={}) for n in EXPECTED_SHEETS]):
            table=QTableWidget();enable_cell_editing(table);table.setAlternatingRowColors(False)
            table.setAcceptDrops(False);table.viewport().setAcceptDrops(False)
            table.setRowCount(sheet['rows']);table.setColumnCount(sheet['cols'])
            table.setHorizontalHeaderLabels([get_column_letter(c+1) for c in range(sheet['cols'])]);table.verticalHeader().setDefaultSectionSize(32)
            table.horizontalHeader().setDefaultSectionSize(130)
            table.setWordWrap(True)
            table.order_groups,table.order_columns,table.header_row=order_groups(sheet)
            table.setItemDelegate(OrderHierarchyDelegate(table))
            styles=(self.payload or {}).get('display_styles',[])
            entries={a:{'s':s} for a,s in sheet.get('layout',{}).get('cell_styles',{}).items()}
            entries.update({a:{} for a in sheet.get('format_edits',{})})
            entries.update(sheet['cells'])
            for address,entry in entries.items():
                from openpyxl.utils.cell import coordinate_to_tuple
                r,c=coordinate_to_tuple(address)
                if r>sheet['rows'] or c>sheet['cols']:continue
                item=QTableWidgetItem(displayed(sheet,address));item.setToolTip(entry.get('f') or str(entry.get('v') or ''))
                if 'f' in entry:item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                style=effective_style(self.payload,sheet,address);apply_item_style(table,item,style,self.show_colors.isChecked())
                override=sheet.get('format_edits',{}).get(address,{})
                item.setData(EXPLICIT_BOLD,override.get('bold'))
                if r<=table.header_row and 'bold' not in override:
                    font=QFont(item.font());font.setBold(True);item.setFont(font)
                table.setItem(r-1,c-1,item)
            layout=sheet.get('layout',{})
            for col in layout.get('columns',[]):
                width=max(78,min(500,round(col['width']*8+12)))
                for c in range(max(1,col['first']),min(sheet['cols'],col['last'])+1):table.setColumnWidth(c-1,width)
            if '订单号' in table.order_columns:
                c=table.order_columns['订单号']-1
                width=max([160]+[table.fontMetrics().horizontalAdvance(g['number'])+28 for g in table.order_groups])
                table.setColumnWidth(c,min(300,max(table.columnWidth(c),width)))
            for r in range(sheet['rows']):
                height=layout.get('heights',{}).get(str(r+1),layout.get('default_height',24));table.setRowHeight(r,max(32,min(180,round(height*4/3))))
            for left,top,right,bottom in merge_ranges(sheet):
                table.setSpan(top-1,left-1,bottom-top+1,right-left+1)
                if top<table.header_row and bottom==top:
                    cell=table.item(top-1,left-1)
                    if cell and not sheet.get('format_edits',{}).get(f'{get_column_letter(left)}{top}'):
                        font=QFont(cell.font());font.setBold(True);font.setPixelSize(18);cell.setFont(font);cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter);table.setRowHeight(top-1,max(44,table.rowHeight(top-1)))
            table.itemSelectionChanged.connect(self.show_relationship)
            table.itemSelectionChanged.connect(self.format_bar.sync)
            table.itemChanged.connect(lambda item,t=table:self.inline_changed(t,item))
            table.clear_contents=lambda t=table:self.clear_selected(t)
            table.remove_plan_records=self.remove_selected_records
            table.viewport().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            table.viewport().customContextMenuRequested.connect(lambda point,t=table:self.cell_menu(t,point))
            self.tables.append(table);self.tabs.addTab(table,sheet['name'])
            if len(positions)>=len(self.tables):
                row,col,vertical,horizontal,ranges=positions[len(self.tables)-1]
                if row<table.rowCount() and col<table.columnCount() and row>=0 and col>=0:table.setCurrentCell(row,col)
                for selected in ranges:
                    if selected.bottomRow()<table.rowCount() and selected.rightColumn()<table.columnCount():table.setRangeSelected(selected,True)
                table.verticalScrollBar().setValue(vertical);table.horizontalScrollBar().setValue(horizontal)
            apply_dimensions(table,sheet);table._format_header=HeaderSizing(self.formatter,table)
        if 0<=previous<self.tabs.count():self.tabs.setCurrentIndex(previous)
        if self.payload:self.info.setText(f"{self.payload['name']} · {len(self.payload['sheets'])} 张可见工作表 · 原文件未改动")
        for control in (self.save_button,self.export_button,self.clear_button,self.remove_button):control.setEnabled(bool(self.payload))
        self.save_action.setEnabled(bool(self.payload));self.filter_rows();self.format_bar.sync();self.show_saved()

    def show_saved(self):
        if not self.payload:self.saved_info.setText('导入计划总表后，可自动保存到本机。');return
        at=self.store.get('planbook_saved_at')
        text=('最近保存：'+at.replace('T',' ')+'。') if at else ''
        self.saved_info.setText('自动保存到本机。'+text+'生成 Excel 文件请使用“导出”。')

    def save_current(self,*args):
        if not self.payload:return False
        try:
            self.last_edit_failed=False
            for table in self.tables:
                editor=next((e for e in table.findChildren(QLineEdit) if e.isVisible()),None)
                if editor is not None and table.state()==QAbstractItemView.State.EditingState:
                    delegate=table.itemDelegateForIndex(table.currentIndex());delegate.commitData.emit(editor);delegate.closeEditor.emit(editor,QAbstractItemDelegate.EndEditHint.NoHint)
                    if self.last_edit_failed:return False
                if hasattr(table,'_format_header') and not table._format_header.flush():return False
            self.format_bar.size.interpretText();self.format_bar.change_size()
            self.store.save_planbook(self.payload);self.show_saved();self.status.setText('已保存到本机；下次打开可继续。需要 Excel 文件请点击“导出”。')
            return True
        except Exception as exc:self.status.setText('保存未完成：'+str(exc));return False

    def cell_menu(self,table,point):
        index=table.indexAt(point)
        if index.isValid() and not table.selectionModel().isSelected(index):table.setCurrentCell(index.row(),index.column())
        menu=QMenu(table);menu.addAction('清空所选内容',lambda:self.clear_selected(table));menu.addAction('移除所选行的计划记录',self.remove_selected_records)
        menu.addSeparator();menu.addAction('保存到本机',self.save_current);menu.addAction('导出',self.export_book);menu.exec(table.viewport().mapToGlobal(point))

    def refresh_values(self,payload):
        """清空时保留当前表格和选区，避免每次 Delete 都重建所有页面。"""
        from openpyxl.utils.cell import coordinate_to_tuple
        self.payload=payload
        for table,sheet in zip(self.tables,payload['sheets']):
            with QSignalBlocker(table):
                for address,entry in sheet['cells'].items():
                    r,c=coordinate_to_tuple(address);item=table.item(r-1,c-1)
                    if item is not None:
                        value=displayed(sheet,address)
                        if item.text()!=value:item.setText(value)
                        item.setToolTip(entry.get('f') or str(entry.get('v') or ''))
            table.order_groups,table.order_columns,table.header_row=order_groups(sheet);table.itemDelegate().rebuild();table.viewport().update()
        self.filter_rows();self.format_bar.sync();self.show_saved()

    def clear_selected(self,table=None):
        if not self.payload:return False
        table=table or self.tables[self.tabs.currentIndex()]
        if table not in self.tables:return False
        try:
            from .plan_operations import clear_plan_cells
            index=self.tables.index(table);points=selected_cells(table,self.payload['sheets'][index])
            updated,orders,count,skipped=clear_plan_cells(self.payload,index,points,self.store.orders())
            if not count:self.status.setText('没有可清空的输入内容；公式格会保留。');return False
            history=getattr(self.main,'edit_history',None);snapshot=history.capture([o['id'] for o in orders],plan=True) if history else None
            self.store.save_plan_edit(updated,orders,'清空计划表所选内容')
            if history:history.record('清空计划表所选内容',snapshot)
            self.refresh_values(updated)
            if orders and hasattr(self.main,'refresh'):self.main.load_daily();self.main.refresh()
            self.status.setText(f'已清空 {count} 格并保存到本机'+(f'，保留 {skipped} 个公式格' if skipped else '')+'；可 Ctrl+Z 撤销。');return True
        except Exception as exc:self.status.setText('未清空：'+str(exc));return False

    def remove_selected_records(self,*args):
        if not self.payload:return False
        index=self.tabs.currentIndex();table=self.tables[index]
        rows={r+1 for area in table.selectedRanges() for r in range(area.topRow(),area.bottomRow()+1) if not table.isRowHidden(r)}
        if not rows and table.currentRow()>=0:rows={table.currentRow()+1}
        try:
            from .plan_operations import remove_plan_records
            updated,orders,count,links=remove_plan_records(self.payload,index,rows,self.store.orders())
            if not count and not links:self.status.setText('所选行没有可移除的计划记录；公式和空行保留。');return False
            text=f'移除“{self.payload["sheets"][index]["name"]}”中所选 {len(rows)} 行的计划记录？\n\n清空计划输入值，解除这几行的订单关联。保留空行、行号、格式和公式；其他明细共用的合并内容也保留。\n订单管理中的原订单、型号和包材保留。操作前自动备份，完成后可 Ctrl+Z 撤销。'
            if QMessageBox.question(self,'移除计划记录',text,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return False
            history=getattr(self.main,'edit_history',None);snapshot=history.capture([o['id'] for o in orders],plan=True) if history else None
            self.store.backup();self.store.save_plan_edit(updated,orders,'移除计划记录（保留行号与原订单）')
            if history:history.record('移除计划记录',snapshot)
            self.refresh_values(updated)
            if hasattr(self.main,'refresh'):self.main.load_daily();self.main.refresh()
            self.status.setText(f'已移除 {len(rows)} 行计划记录并保存；原订单、空行和公式保留，可 Ctrl+Z 撤销。');return True
        except Exception as exc:self.status.setText('未移除：'+str(exc));return False

    def toggle_colors(self,checked):
        self.store.set('plan_show_colors','1' if checked else '0');self.reload()

    def selected_link(self):
        if self.tabs.currentIndex()<0:return None
        table=self.tables[self.tabs.currentIndex()];r=table.currentRow()
        return next((l for l in (self.payload or {}).get('order_links',[]) if l['sheet']==self.tabs.tabText(self.tabs.currentIndex()) and l['row']==r+1),None)

    def show_relationship(self):
        index=self.tabs.currentIndex()
        if index<0 or index>=len(self.tables):return
        table=self.tables[index];r=table.currentRow()+1
        if r>0 and self.payload and hasattr(self,'cell_value'):
            row,col=anchor_cell(self.payload['sheets'][index],r,table.currentColumn()+1);address=f'{get_column_letter(col)}{row}';entry=self.payload['sheets'][index]['cells'].get(address,{})
            self.cell_address.setText(address+(' · 公式只读' if 'f' in entry else ' · 完整内容'));self.cell_value.setText(entry.get('f') or str(entry.get('v') if entry.get('v') is not None else ''));self.cell_value.setToolTip(self.cell_value.text())
        group=next((g for g in table.order_groups if g['start']<=r<=g['end']),None)
        if group:self.relationship.setText(f"所属订单：{group['number']}  →  下属明细 {group['end']-group['start']+1} 行（第 {group['start']}–{group['end']} 行）；型号列的分支线表示该订单的子项。")
        else:self.relationship.setText('选择明细可查看所属订单及同组明细范围。')

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
        self.store.backup();self.store.save_planbook(payload,source);self.reload();self.status.setText('导入完成。单击选择，直接键入替换；双击或 F2 编辑原内容。')
        if hasattr(self.main,'confirm_plan_join') and self.store.orders():
            self.main.refresh();self.main.confirm_plan_join()

    def export_book(self):
        if not self.payload or not self.save_current():return
        from .plan_export import ExportScopeDialog
        names=[s['name'] for s in self.payload['sheets']];scope=ExportScopeDialog(names,names[self.tabs.currentIndex()],self)
        if not scope.exec():return
        chosen=scope.selected_names
        suffix='.xlsm' if self.payload['name'].lower().endswith('.xlsm') else '.xlsx'
        path,_=QFileDialog.getSaveFileName(self,'另存完整计划总表','计划总表_工作台'+suffix,'Excel (*'+suffix+')')
        if not path:return
        payload=copy.deepcopy(self.payload);source=self.store.planbook_source();self.status.setText(f'正在导出 {len(chosen)} 张工作表……')
        self.run_job(lambda:export_planbook(path,payload,source,chosen),lambda _:self.status.setText(f'已导出 {len(chosen)} 张工作表：'+path+'；请用 WPS / Excel 打开重新计算公式。'))

    def edit_selected(self):
        if not self.payload:return
        index=self.tabs.currentIndex();table=self.tables[index];r,c=table.currentRow(),table.currentColumn()
        if r<0 or c<0:return
        sheet=self.payload['sheets'][index];anchor_row,anchor_col=anchor_cell(sheet,r+1,c+1);r,c=anchor_row-1,anchor_col-1
        address=f'{get_column_letter(c+1)}{r+1}';entry=sheet['cells'].get(address,{})
        if 'f' in entry:QMessageBox.information(self,'原表公式',entry.get('f') or '此格为原表共享公式。请修改相应输入格，导出后由 Excel 重算。');return
        dialog=QDialog(self);dialog.setWindowTitle(sheet['name']+' · '+address);dialog.resize(520,280);box=QVBoxLayout(dialog)
        editor=QTextEdit(str(entry.get('v') if entry.get('v') is not None else ''));box.addWidget(editor)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);box.addWidget(buttons)
        if not dialog.exec():return
        self.commit_cell(index,r,c,editor.toPlainText())

    def inline_changed(self,table,item):
        if getattr(self,'saving_cell',False) or table not in self.tables:return
        self.commit_cell(self.tables.index(table),item.row(),item.column(),item.text())

    def commit_cell(self,index,row,column,text):
        if not self.payload:return False
        source=self.payload['sheets'][index];r,c=anchor_cell(source,row+1,column+1);address=f'{get_column_letter(c)}{r}'
        old=displayed(source,address)
        if text==old:return True
        table=self.tables[index]
        try:
            entry=source['cells'].get(address,{})
            if 'f' in entry:raise ValueError('公式格由计算产生，请修改对应输入格。')
            from .plan_sync import headers
            columns,header= headers(source);field=next((name for name,col in columns.items() if col==c),'') if r>header else ''
            value=plan_value(text,entry,field,source['name'])
            updated=copy.deepcopy(self.payload);sheet=updated['sheets'][index]
            before={o['id']:o for o in self.store.orders()}
            orders=linked_plan_orders(updated,sheet,r,c,field,value,list(before.values()))
            from datetime import date
            day=date.today().isoformat();daily={}
            for order in orders:
                prior={i['id']:i.get('analyzed') for i in before[order['id']]['items']}
                if any(i.get('analyzed') and not prior.get(i['id']) for i in order['items']):
                    from .edit_history import analysis_followup
                    daily[day]=analysis_followup(order,daily.get(day,self.store.daily(day)))
            history=getattr(self.main,'edit_history',None)
            snapshot=history.capture([o['id'] for o in orders],plan=True,days=daily) if history else None
            edit_cell(sheet,address,value)
            for s in updated['sheets']:s['formulas_stale']=True
            label=f'计划表 {sheet["name"]}!{address}'
            self.store.save_plan_edit(updated,orders,label,daily=daily)
            if history:history.record(label,snapshot)
            self.payload=updated
        except Exception as exc:
            self.last_edit_failed=True
            with QSignalBlocker(table):
                item=table.item(r-1,c-1)
                if item:item.setText(old)
            message='订单号已存在，请使用其他订单号。' if 'UNIQUE' in str(exc) else str(exc)
            self.status.setText('未保存：'+message)
            return False
        with QSignalBlocker(table):
            item=table.item(r-1,c-1)
            if item is None:item=QTableWidgetItem();table.setItem(r-1,c-1,item)
            item.setText(displayed(sheet,address));item.setToolTip(str(value))
            self.show_saved()
            self.show_relationship()
            for si,s in enumerate(updated['sheets']):
                for a,e in s['cells'].items():
                    if 'f' in e:
                        from openpyxl.utils.cell import coordinate_to_tuple
                        fr,fc=coordinate_to_tuple(a);cell=self.tables[si].item(fr-1,fc-1)
                        if cell:
                            with QSignalBlocker(self.tables[si]):cell.setText(displayed(s,a))
        def finish():
            if table not in self.tables or getattr(self.main,'quitting',False):return
            current=self.payload['sheets'][self.tables.index(table)]
            table.order_groups,table.order_columns,table.header_row=order_groups(current);table.itemDelegate().rebuild();table.viewport().update()
            self.show_relationship()
            if orders and hasattr(self.main,'refresh'):
                self.main.load_daily();self.main.refresh()
            if self.payload is updated:self.status.setText(f'已保存 {sheet["name"]}!{address}'+('；订单已同步，其他关联计划行请确认更新。' if orders else '。'))
        QTimer.singleShot(0,finish)
        return True

    def add_row(self):
        if not self.payload:return
        history=getattr(self.main,'edit_history',None);snapshot=history.capture(plan=True) if history else None
        index=self.tabs.currentIndex();sheet=self.payload['sheets'][index];sheet['rows']+=1
        self.store.save_planbook(self.payload)
        if history:history.record('计划表新增一行',snapshot)
        self.reload();self.tabs.setCurrentIndex(index)
        table=self.tables[index];table.setCurrentCell(sheet['rows']-1,0);table.scrollToBottom();self.status.setText('已新增空行；选中后直接键入，或双击 / F2 编辑。')

    def filter_rows(self,*args):
        index=self.tabs.currentIndex()
        if index<0 or index>=len(self.tables):return
        table=self.tables[index];text=self.search.text().strip().lower()
        matched=set()
        if text:
            # 整个订单一起显示，避免只剩命中型号而丢失其父项。
            for group in table.order_groups:
                if text in group['context'].lower() or any(text in table.item(r-1,c).text().lower() for r in range(group['start'],group['end']+1) for c in range(table.columnCount()) if table.item(r-1,c)):
                    matched.update(range(group['start'],group['end']+1))
        for r in range(table.rowCount()):
            visible=not text or r+1<=table.header_row or r+1 in matched or any(text in table.item(r,c).text().lower() for c in range(table.columnCount()) if table.item(r,c))
            table.setRowHidden(r,not visible)
        self.status.setText(f'当前工作表：{table.rowCount()} 行、{table.columnCount()} 列 · {len(table.order_groups)} 个订单分组')
        self.show_relationship()
