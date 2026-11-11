"""接近常用电子表格的文字和单元格尺寸工具。"""
import copy
from PySide6.QtCore import Qt,QSignalBlocker,QTimer,QEvent,QObject
from PySide6.QtGui import QFont,QColor,QAction,QKeySequence
from PySide6.QtWidgets import (QWidget,QHBoxLayout,QVBoxLayout,QLabel,QFontComboBox,QDoubleSpinBox,
    QPushButton,QComboBox,QColorDialog,QInputDialog,QTableWidgetItem,QMenu,QStyleOptionViewItem,QStyleFactory,QStyle,QAbstractItemView)
from openpyxl.utils.cell import get_column_letter
from .cell_format import selected_cells,effective_style,update_formats
from .inline_edit import SpreadsheetDelegate

EXPLICIT_BOLD=Qt.ItemDataRole.UserRole+20
WRAP_ROLE=Qt.ItemDataRole.UserRole+21


def apply_item_style(table,item,style,colors=True):
    font=QFont(table.font())
    if style.get('family'):font.setFamily(style['family'])
    font.setPointSizeF(float(style.get('size',10)));font.setBold(style.get('bold',False));font.setItalic(style.get('italic',False));font.setUnderline(style.get('underline',False))
    item.setFont(font)
    item.setData(Qt.ItemDataRole.BackgroundRole,QColor(style['background']) if colors and style.get('background') else None)
    item.setData(Qt.ItemDataRole.ForegroundRole,QColor(style['foreground']) if colors and style.get('foreground') else None)
    alignment=style.get('alignment',{})
    h={'center':Qt.AlignmentFlag.AlignHCenter,'right':Qt.AlignmentFlag.AlignRight}.get(alignment.get('horizontal'),Qt.AlignmentFlag.AlignLeft)
    v={'top':Qt.AlignmentFlag.AlignTop,'bottom':Qt.AlignmentFlag.AlignBottom}.get(alignment.get('vertical'),Qt.AlignmentFlag.AlignVCenter)
    item.setTextAlignment(h|v);item.setData(WRAP_ROLE,str(alignment.get('wrapText','1')) in ('1','true','True'))


class FormatBar(QWidget):
    def __init__(self,controller,parent=None):
        super().__init__(parent);self.controller=controller;controller.bar=self
        self.setStyleSheet('QPushButton:checked {background:#eaf1fe;border-color:#8fb3ef;color:#245fd1;} QDoubleSpinBox {background:#ffffff;border:1px solid #dbe3ef;border-radius:7px;padding:4px;color:#24344c;}')
        box=QVBoxLayout(self);box.setContentsMargins(0,0,0,0);box.setSpacing(6)
        row=QHBoxLayout();row.setSpacing(6);box.addLayout(row)
        self.font=QFontComboBox();self.font.setFixedWidth(150);self.font.setToolTip('字体');row.addWidget(self.font)
        self.size=QDoubleSpinBox();self.size.setRange(6,72);self.size.setDecimals(1);self.size.setValue(10);self.size.setFixedWidth(75);self.size.setToolTip('字号（磅）');row.addWidget(self.size)
        self.font.currentFontChanged.connect(lambda font:controller.apply({'family':font.family()}))
        self.size.editingFinished.connect(self.change_size)
        self.flags={}
        for text,key,tip in [('B','bold','加粗'),('I','italic','倾斜'),('U','underline','下划线')]:
            b=QPushButton(text);b.setCheckable(True);b.setFixedWidth(40);b.setToolTip(tip)
            f=QFont(b.font());getattr(f,{'bold':'setBold','italic':'setItalic','underline':'setUnderline'}[key])(True);b.setFont(f)
            b.clicked.connect(lambda checked,k=key:controller.apply({k:checked}));row.addWidget(b);self.flags[key]=b
        for text,key in [('文字颜色','foreground'),('填充颜色','background')]:
            b=QPushButton(text);b.clicked.connect(lambda checked=False,k=key:self.choose_color(k));row.addWidget(b)
        self.wrap=QPushButton('自动换行');self.wrap.setCheckable(True);self.wrap.clicked.connect(lambda checked:controller.apply({'wrap':checked}));row.addWidget(self.wrap)
        reset=QPushButton('恢复原格式');reset.setToolTip('恢复所选单元格的初始显示格式，不清空内容');reset.clicked.connect(lambda:controller.apply(reset=True));row.addWidget(reset);row.addStretch()
        row=QHBoxLayout();row.setSpacing(6);box.addLayout(row)
        self.horizontal=QComboBox();self.horizontal.addItems(['左对齐','水平居中','右对齐']);self.horizontal.setFixedWidth(110)
        self.vertical=QComboBox();self.vertical.addItems(['顶部对齐','垂直居中','底部对齐']);self.vertical.setFixedWidth(110)
        row.addWidget(self.horizontal);row.addWidget(self.vertical)
        self.horizontal.activated.connect(lambda index:controller.apply({'horizontal':('left','center','right')[index]}))
        self.vertical.activated.connect(lambda index:controller.apply({'vertical':('top','center','bottom')[index]}))
        for text,axis,fit in [('行高','rows',False),('列宽','columns',False),('适应行高','rows',True),('适应列宽','columns',True)]:
            b=QPushButton(text);b.clicked.connect(lambda checked=False,a=axis,f=fit:controller.fit(a) if f else self.ask_size(a));row.addWidget(b)
        self.selection=QLabel('先选择单元格，可拖动框选或按住 Shift 扩选');row.addWidget(self.selection,1)

    def sync(self):
        table=self.controller.table()
        self.setEnabled(table is not None and table.currentRow()>=0)
        if table is None or table.currentRow()<0:return
        style=self.controller.current_style();font=QFont(table.font())
        if style.get('family'):font.setFamily(style['family'])
        controls=[self.font,self.size,self.wrap,self.horizontal,self.vertical,*self.flags.values()]
        blockers=[QSignalBlocker(c) for c in controls]
        self.font.setCurrentFont(font);self.size.setValue(style.get('size',10));self.loaded_size=self.size.value()
        for key,button in self.flags.items():button.setChecked(style.get(key,False))
        a=style.get('alignment',{});self.horizontal.setCurrentIndex({'center':1,'right':2}.get(a.get('horizontal'),0));self.vertical.setCurrentIndex({'top':0,'bottom':2}.get(a.get('vertical'),1))
        self.wrap.setChecked(str(a.get('wrapText','1')) in ('1','true','True'))
        ranges=table.selectedRanges()
        if ranges:
            r=ranges[0];self.selection.setText(f'{get_column_letter(r.leftColumn()+1)}{r.topRow()+1}:{get_column_letter(r.rightColumn()+1)}{r.bottomRow()+1}'+(' · 多个选区' if len(ranges)>1 else ''))

    def change_size(self):
        if self.size.value()!=getattr(self,'loaded_size',None):self.controller.apply({'size':self.size.value()})

    def choose_color(self,key):
        color=QColorDialog.getColor(QColor(self.controller.current_style().get(key) or ('#ffffff' if key=='background' else '#172b4d')),self,'选择填充颜色' if key=='background' else '选择文字颜色')
        if color.isValid():self.controller.apply({key:color.name()})

    def ask_size(self,axis):
        table=self.controller.table()
        if table is None or table.currentRow()<0:return
        row=axis=='rows';current=table.rowHeight(table.currentRow())*.75 if row else max(.1,(table.columnWidth(table.currentColumn())-12)/8)
        value,ok=QInputDialog.getDouble(self,'设置行高' if row else '设置列宽','行高（磅）' if row else '列宽（字符，近似 WPS）',current,12 if row else 1,409 if row else 255,1)
        if ok:self.controller.resize_selected(axis,round(value*4/3) if row else round(value*8+12))


class HeaderSizing(QObject):
    def __init__(self,controller,table):
        super().__init__(table);self.controller=controller;self.table=table;self.pending={};self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.flush)
        for header,axis in ((table.horizontalHeader(),'columns'),(table.verticalHeader(),'rows')):
            header.setSectionResizeMode(header.ResizeMode.Interactive);header.setMinimumSectionSize(16)
            header.setMaximumSectionSize(545 if axis=='rows' else 2052)
            header.sectionResized.connect(lambda index,old,new,a=axis:self.changed(a,index,new))
            header.viewport().installEventFilter(self)
            # 自己处理双击，保证自动适应作为一次修改入栈。
            try:header.sectionHandleDoubleClicked.disconnect()
            except RuntimeError:pass
            header.sectionHandleDoubleClicked.connect(lambda index,a=axis:controller.fit(a,[index]))
            header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            header.customContextMenuRequested.connect(lambda point,h=header,a=axis:self.menu(h,a,point))
        for key,shortcut in (('bold','Ctrl+B'),('italic','Ctrl+I'),('underline','Ctrl+U')):
            action=QAction(table);action.setShortcut(QKeySequence(shortcut));action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
            action.triggered.connect(lambda checked=False,k=key:controller.apply({k:not controller.current_style().get(k,False)}));table.addAction(action)

    def changed(self,axis,index,new):
        if self.table.signalsBlocked():return
        self.pending.setdefault(axis,{})[str(index+1)]=new;self.timer.start(250)

    def flush(self):
        if not self.pending:return True
        pending=self.pending;self.pending={};self.timer.stop()
        result=self.controller.save_dimensions(pending,self.table)
        if result is False:self.pending=pending
        return result is not False

    def eventFilter(self,obj,event):
        if event.type()==QEvent.Type.MouseButtonRelease:self.flush()
        return False

    def menu(self,header,axis,point):
        index=header.logicalIndexAt(point)
        if index<0:return
        self.flush();table=self.table
        if axis=='rows':
            if not any(r.topRow()<=index<=r.bottomRow() for r in table.selectedRanges()):table.selectRow(index)
        elif not any(r.leftColumn()<=index<=r.rightColumn() for r in table.selectedRanges()):table.selectColumn(index)
        menu=QMenu(table);menu.addAction('设置行高' if axis=='rows' else '设置列宽',lambda:self.controller.bar.ask_size(axis));menu.addAction('按内容自动适应',lambda:self.controller.fit(axis))
        if axis=='rows' and hasattr(table,'remove_plan_records'):
            menu.addSeparator();menu.addAction('移除所选行的计划记录',table.remove_plan_records)
        menu.exec(header.mapToGlobal(point))


class PlanFormatting:
    def __init__(self,owner):self.owner=owner;self.bar=None
    def table(self):
        i=self.owner.tabs.currentIndex()
        return self.owner.tables[i] if 0<=i<len(self.owner.tables) and self.owner.payload else None
    def sheet(self,table=None):return self.owner.payload['sheets'][self.owner.tables.index(table or self.table())]
    def current_style(self):
        table=self.table();sheet=self.sheet();points=selected_cells(table,sheet)
        if not points:return {}
        r,c=points[0];return effective_style(self.owner.payload,sheet,f'{get_column_letter(c)}{r}')
    def apply(self,changes=None,reset=False):
        table=self.table()
        if table is None:return
        try:
            sheet=self.sheet();points=selected_cells(table,sheet)
            if not points:return
            history=getattr(self.owner.main,'edit_history',None);before=history.capture(plan=True) if history else None
            payload=copy.deepcopy(self.owner.payload);target=payload['sheets'][self.owner.tables.index(table)]
            update_formats(target,points,changes,reset)
            self.owner.store.save_planbook(payload);self.owner.payload=payload
            if history:history.record('计划表恢复原格式' if reset else '计划表单元格格式',before)
            if changes and set(changes)&{'foreground','background'} and not self.owner.show_colors.isChecked():
                with QSignalBlocker(self.owner.show_colors):self.owner.show_colors.setChecked(True)
                self.owner.store.set('plan_show_colors','1');self.owner.reload();table=self.table()
            with QSignalBlocker(table):
                for r,c in points:
                    item=table.item(r-1,c-1)
                    if item is None:item=QTableWidgetItem();table.setItem(r-1,c-1,item)
                    address=f'{get_column_letter(c)}{r}';style=effective_style(payload,target,address)
                    apply_item_style(table,item,style,self.owner.show_colors.isChecked())
                    override=target.get('format_edits',{}).get(address,{})
                    item.setData(EXPLICIT_BOLD,override.get('bold'))
                    if r<=table.header_row and 'bold' not in override:
                        font=QFont(item.font());font.setBold(True);item.setFont(font)
                    if r<table.header_row and table.columnSpan(r-1,c-1)>1 and not override:
                        font=QFont(item.font());font.setBold(True);font.setPixelSize(18);item.setFont(font);item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.bar.sync();table.viewport().update();self.owner.status.setText(f'已保存 {len(points)} 格格式；支持撤销 / 重做，导出保留。')
            if hasattr(self.owner,'show_saved'):self.owner.show_saved()
        except Exception as exc:self.owner.status.setText('未保存格式：'+str(exc))
    def indices(self,axis):
        table=self.table();ranges=table.selectedRanges();row=axis=='rows'
        return sorted({index for r in ranges for index in range(r.topRow() if row else r.leftColumn(),(r.bottomRow() if row else r.rightColumn())+1)}) or ([table.currentRow() if row else table.currentColumn()] if table.currentRow()>=0 else [])
    def resize_selected(self,axis,pixels):self.save_dimensions({axis:{str(i+1):pixels for i in self.indices(axis)}})
    def fit(self,axis,indices=None):
        table=self.table()
        if table is None:return
        if hasattr(table,'_format_header'):
            table._format_header.timer.stop();table._format_header.pending={}
        indices=self.indices(axis) if indices is None else indices;header=table.verticalHeader() if axis=='rows' else table.horizontalHeader()
        values={}
        with QSignalBlocker(header):
            for index in indices:
                if axis=='rows':table.resizeRowToContents(index);value=max(24,min(545,table.rowHeight(index)))
                else:table.resizeColumnToContents(index);value=max(32,min(2052,table.columnWidth(index)))
                values[str(index+1)]=value
        self.save_dimensions({axis:values})
    def save_dimensions(self,dimensions,table=None):
        table=table or self.table()
        if table is None or table not in self.owner.tables:return
        try:
            history=getattr(self.owner.main,'edit_history',None);before=history.capture(plan=True) if history else None
            payload=copy.deepcopy(self.owner.payload);sheet=payload['sheets'][self.owner.tables.index(table)]
            edits=sheet.setdefault('dimension_edits',{})
            for axis,values in dimensions.items():edits.setdefault(axis,{}).update(values)
            self.owner.store.save_planbook(payload);self.owner.payload=payload
            if history:history.record('计划表行高 / 列宽',before)
            apply_dimensions(table,sheet)
            self.owner.status.setText('行高 / 列宽已保存；支持撤销 / 重做，导出保留。')
            if hasattr(self.owner,'show_saved'):self.owner.show_saved()
            return True
        except Exception as exc:self.owner.status.setText('未保存尺寸：'+str(exc));return False


def apply_dimensions(table,sheet):
    with QSignalBlocker(table.horizontalHeader()),QSignalBlocker(table.verticalHeader()):
        for axis,values in sheet.get('dimension_edits',{}).items():
            for index,pixels in values.items():
                if axis=='rows' and 0<int(index)<=table.rowCount():table.setRowHeight(int(index)-1,pixels)
                elif axis=='columns' and 0<int(index)<=table.columnCount():table.setColumnWidth(int(index)-1,pixels)


class FormattedDelegate(SpreadsheetDelegate):
    def __init__(self,table):
        super().__init__(table);self.style=QStyleFactory.create('Fusion');self.style.setParent(self)
    def initStyleOption(self,option,index):
        super().initStyleOption(option,index)
        wrap=index.data(WRAP_ROLE)
        if wrap is not None:
            if wrap:option.features |= QStyleOptionViewItem.ViewItemFeature.WrapText
            else:option.features &= ~QStyleOptionViewItem.ViewItemFeature.WrapText
    def paint(self,painter,option,index):
        option=QStyleOptionViewItem(option);self.initStyleOption(option,index);option.state &= ~QStyle.StateFlag.State_MouseOver
        from PySide6.QtGui import QPalette
        option.palette.setColor(QPalette.ColorRole.Base,QColor('#ffffff'));option.palette.setColor(QPalette.ColorRole.Highlight,QColor('#dce9ff'));option.palette.setColor(QPalette.ColorRole.HighlightedText,QColor('#16202f'))
        self.style.drawControl(QStyle.ControlElement.CE_ItemViewItem,option,painter,self.parent())
        from .ux_controls import paint_current_cell
        paint_current_cell(painter,option,index,self.parent())


class ViewFormatting(PlanFormatting):
    """订单、包材格式按稳定业务标识保存，筛选和排序不串行。"""
    def __init__(self,table,main,name):
        self.grid=table;self.main=main;self.name=name;self.bar=None
        self.base_widths={str(i+1):table.columnWidth(i) for i in range(table.columnCount())}
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems);table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setItemDelegate(FormattedDelegate(table));table.setWordWrap(True)
        table.itemSelectionChanged.connect(self.sync)
        table._format_header=HeaderSizing(self,table)
    def table(self):return self.grid
    def sync(self):
        if self.bar:self.bar.sync()
    def row_key(self,row):
        item=self.grid.item(row,0)
        return f'{item.data(Qt.ItemDataRole.UserRole)}:{item.data(Qt.ItemDataRole.UserRole+1)}' if item else ''
    def key(self,row,col):return self.row_key(row)+':'+str(col)
    def current_style(self):
        table=self.grid;item=table.currentItem();font=item.font() if item else table.font()
        style=dict(family=font.family(),size=font.pointSizeF() if font.pointSizeF()>0 else max(6,font.pixelSize()*.75),bold=font.bold(),italic=font.italic(),underline=font.underline(),alignment={})
        if item:
            a=item.textAlignment();style['alignment']=dict(horizontal='center' if a & Qt.AlignmentFlag.AlignHCenter else 'right' if a & Qt.AlignmentFlag.AlignRight else 'left',vertical='top' if a & Qt.AlignmentFlag.AlignTop else 'bottom' if a & Qt.AlignmentFlag.AlignBottom else 'center',wrapText=str(int(bool(item.data(WRAP_ROLE)))))
        style.update(self.main.store.table_format(self.name).get('cells',{}).get(self.key(table.currentRow(),table.currentColumn()),{}))
        return style
    def apply(self,changes=None,reset=False):
        from .cell_format import validate_format
        try:
            if changes:validate_format(changes)
            points=selected_cells(self.grid)
            if not points:return
            before=self.main.edit_history.capture(views=[self.name]);payload=self.main.store.table_format(self.name);edits=payload.setdefault('cells',{})
            for r,c in points:
                key=self.key(r-1,c-1)
                if reset:edits.pop(key,None)
                else:edits.setdefault(key,{}).update(changes)
            self.main.store.save_table_format(self.name,payload);self.main.edit_history.record('订单管理格式' if self.name=='orders' else '包材明细格式',before)
            self.main.refresh();self.sync();self.main.status.showMessage(f'已保存 {len(points)} 格格式，支持撤销 / 重做。',7000)
        except Exception as exc:self.main.status.showMessage('未保存格式：'+str(exc),10000)
    def save_dimensions(self,dimensions,table=None):
        if table is not None and table is not self.grid:return
        try:
            before=self.main.edit_history.capture(views=[self.name]);payload=self.main.store.table_format(self.name)
            for axis,values in dimensions.items():
                target=payload.setdefault(axis,{})
                for index,pixels in values.items():
                    key=self.row_key(int(index)-1) if axis=='rows' else index
                    if key:target[key]=pixels
            self.main.store.save_table_format(self.name,payload);self.main.edit_history.record('订单行高 / 列宽' if self.name=='orders' else '包材行高 / 列宽',before)
            self.apply_saved();self.main.status.showMessage('行高 / 列宽已保存，支持撤销 / 重做。',7000)
        except Exception as exc:self.main.status.showMessage('未保存尺寸：'+str(exc),10000)
    def apply_saved(self):
        payload=self.main.store.table_format(self.name);table=self.grid
        with QSignalBlocker(table),QSignalBlocker(table.horizontalHeader()),QSignalBlocker(table.verticalHeader()):
            for row in range(table.rowCount()):
                table.setRowHeight(row,payload.get('rows',{}).get(self.row_key(row),32))
                for col in range(table.columnCount()):
                    item=table.item(row,col);style=payload.get('cells',{}).get(self.key(row,col))
                    if item is None or not style:continue
                    base=dict(family=table.font().family(),size=10,bold=False,italic=False,underline=False,alignment={})
                    # 未指定的颜色/对齐沿用业务提示（例如未到数量的红字）。
                    if item.foreground().style().value:base['foreground']=item.foreground().color().name()
                    alignment=item.textAlignment();base['alignment'].update(horizontal='right' if alignment & Qt.AlignmentFlag.AlignRight else 'center' if alignment & Qt.AlignmentFlag.AlignHCenter else 'left')
                    for key,value in style.items():
                        if key in ('horizontal','vertical','wrap'):base['alignment']['wrapText' if key=='wrap' else key]=str(int(value)) if key=='wrap' else value
                        else:base[key]=value
                    apply_item_style(table,item,base)
            for index,pixels in {**self.base_widths,**payload.get('columns',{})}.items():
                if 0<int(index)<=table.columnCount():table.setColumnWidth(int(index)-1,pixels)
        self.sync()
