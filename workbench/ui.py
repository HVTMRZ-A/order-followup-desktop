import copy
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from PySide6.QtCore import Qt, QDate, QDateTime, QTimer, QThread, Signal, QUrl
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap, QDesktopServices, QAction
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QComboBox, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QDialog, QDialogButtonBox, QFormLayout, QTabWidget, QTextEdit, QCheckBox, QDateEdit, QDateTimeEdit,
    QFileDialog, QMessageBox, QListWidget, QStackedWidget, QFrame, QGridLayout, QSystemTrayIcon, QMenu)
from . import VERSION, APP_NAME, REPOSITORY
from .domain import new_order, new_item, uid, validate_order, demand, fmt, reminders, all_checked, progress, confirm_all
from .storage import Store, data_dir
from .importer import read_import, write_template
from . import updater

STYLE = '''
QWidget { font-family: "Microsoft YaHei UI"; font-size: 13px; color: #26364b; }
QMainWindow, QDialog { background: #f4f6fa; }
QLabel#title { font-size: 25px; font-weight: 600; color: #142a45; }
QLabel#muted { color: #718096; }
QLabel#stat { font-size: 30px; font-weight: 600; color: #173d69; }
QFrame#card { background: white; border: 1px solid #e4e9f1; border-radius: 10px; }
QListWidget#nav { background: #142a45; color: #bccadd; border: none; padding: 12px 8px; font-size: 15px; }
QListWidget#nav::item { padding: 15px 14px; margin: 3px 2px; border-radius: 6px; }
QListWidget#nav::item:selected { background: #285780; color: white; }
QPushButton { background: white; border: 1px solid #d6dfeb; border-radius: 6px; padding: 8px 15px; }
QPushButton:hover { background: #edf4ff; border-color: #8eafdb; }
QPushButton#primary { background: #2266ae; color: white; border-color: #2266ae; }
QPushButton#primary:hover { background: #1a5594; }
QPushButton:disabled { color: #97a4b4; background: #edf0f4; }
QLineEdit, QComboBox, QDateEdit, QDateTimeEdit, QTextEdit { background: white; border: 1px solid #d6dfeb; border-radius: 5px; padding: 7px; selection-background-color: #2266ae; }
QTableWidget { background: white; alternate-background-color: #f8fafd; border: 1px solid #e0e6ef; border-radius: 6px; gridline-color: #edf0f5; selection-background-color: #e4effe; selection-color: #173d69; }
QHeaderView::section { background: #edf2f8; color: #53677e; padding: 10px 8px; border: none; border-bottom: 1px solid #dce4ef; font-weight: 600; }
QTabWidget::pane { background: white; border: 1px solid #dce4ef; border-radius: 5px; }
QTabBar::tab { padding: 11px 18px; background: #edf2f8; }
QTabBar::tab:selected { background: white; color: #2266ae; }
QCheckBox { spacing: 7px; padding: 4px; }
QCheckBox::indicator { width: 17px; height: 17px; }
QStatusBar { background: #eaf0f7; color: #64748b; }
'''


def icon():
    pix = QPixmap(64, 64); pix.fill(Qt.GlobalColor.transparent)
    paint = QPainter(pix); paint.setRenderHint(QPainter.RenderHint.Antialiasing)
    paint.setPen(Qt.PenStyle.NoPen); paint.setBrush(QColor("#2266ae")); paint.drawRoundedRect(0, 0, 64, 64, 14, 14)
    paint.setPen(QColor("white")); paint.setFont(QFont("Microsoft YaHei UI", 27, QFont.Weight.Bold)); paint.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "单"); paint.end()
    return QIcon(pix)


def button(text, callback, primary=False):
    b = QPushButton(text)
    if primary: b.setObjectName("primary")
    b.clicked.connect(callback)
    return b


def label(text, name=None):
    w = QLabel(text); w.setWordWrap(True)
    if name: w.setObjectName(name)
    return w


def table(headers):
    t = QTableWidget(0, len(headers)); t.setHorizontalHeaderLabels(headers)
    t.setAlternatingRowColors(True); t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.verticalHeader().hide(); t.verticalHeader().setDefaultSectionSize(43)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    t.horizontalHeader().setStretchLastSection(True)
    return t


def put(t, row, values, identity=None):
    t.insertRow(row)
    for col, value in enumerate(values):
        item = QTableWidgetItem(str(value)); item.setToolTip(str(value)); item.setData(Qt.ItemDataRole.UserRole, identity)
        t.setItem(row, col, item)


def date_field(value="", optional=False):
    if optional:
        w = QLineEdit(value); w.setPlaceholderText("YYYY-MM-DD（可留空）"); return w
    w = QDateEdit(); w.setCalendarPopup(True); w.setDisplayFormat("yyyy-MM-dd")
    w.setDate(QDate.fromString(value, "yyyy-MM-dd") if value else QDate.currentDate()); return w


class ItemDialog(QDialog):
    def __init__(self, item, parent):
        super().__init__(parent); self.setWindowTitle("型号与确认项"); self.resize(460, 410); self.item = copy.deepcopy(item)
        layout = QVBoxLayout(self); form = QFormLayout(); layout.addLayout(form)
        self.model = QLineEdit(item["model"]); self.qty = QLineEdit(item["quantity"])
        form.addRow("产品型号 *", self.model); form.addRow("产品数量 *", self.qty)
        self.flags = {}
        for key, title in [("bom", "工程 BOM 已匹配"), ("analyzed", "分析已完成"), ("packaging", "包材信息已确认"), ("completed", "该型号跟进完成")]:
            w = QCheckBox(title); w.setChecked(item.get(key, False)); form.addRow(w); self.flags[key] = w
        self.analysis_date = date_field(item.get("analysis_at", "")); form.addRow("分析日期", self.analysis_date)
        layout.addWidget(label("勾选分析完成后，包材信息的 10 天期限从此日期计算。", "muted"))
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept); box.rejected.connect(self.reject); layout.addWidget(box)

    def value(self):
        self.item.update(model=self.model.text().strip(), quantity=self.qty.text().strip())
        self.item.update({key:w.isChecked() for key,w in self.flags.items()})
        self.item["analysis_at"] = self.analysis_date.date().toString("yyyy-MM-dd") if self.item["analyzed"] else ""
        return self.item


class MaterialDialog(QDialog):
    def __init__(self, order, material, parent):
        super().__init__(parent); self.setWindowTitle("包材请购与到料"); self.resize(560, 640)
        self.order = order; self.material = copy.deepcopy(material or dict(id=uid(), name="", usage="1", arrived="0"))
        layout = QVBoxLayout(self); form = QFormLayout(); layout.addLayout(form)
        self.model = QComboBox()
        for item in order["items"]: self.model.addItem(f"{item['model']}（产品数量 {item['quantity']}）", item["id"])
        self.model.setCurrentIndex(max(0,self.model.findData(self.material.get("item_id"))))
        form.addRow("关联型号", self.model); self.fields = {}
        for key, title, default in [("name", "包材名称 *", ""), ("usage", "单个产品使用量 *", "1"), ("unit", "计量单位", "个"),
                                    ("request_no", "请购单号", ""), ("request_date", "请购日期", ""), ("buyer", "采购经办人", ""),
                                    ("due_date", "预计到料日期", ""), ("remind_date", "提醒日期", ""), ("arrived", "累计已到数量", "0"),
                                    ("arrival_date", "最近实际到料日期", ""), ("notes", "跟进记录 / 备注", "")]:
            w = QLineEdit(str(self.material.get(key, default))); self.fields[key] = w
            if "date" in key: w.setPlaceholderText("YYYY-MM-DD（可留空）")
            form.addRow(title, w)
        self.calculation = label(""); layout.addWidget(self.calculation)
        layout.addWidget(label("请购数量 = 产品数量 × 单件包材用量，不扣库存。提醒日期留空时使用预计到料日期，提醒时间固定为 09:00。到齐后自动停止该包材提醒。", "muted"))
        self.model.currentIndexChanged.connect(self.calculate); self.fields["usage"].textChanged.connect(self.calculate); self.calculate()
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.save); box.rejected.connect(self.reject); layout.addWidget(box)

    def calculate(self):
        try:
            material = dict(item_id=self.model.currentData(), usage=self.fields["usage"].text())
            qty = demand(self.order, material)
            self.calculation.setText(f"本型号所需请购数量：{fmt(qty)}")
        except Exception: self.calculation.setText("请填写有效的单件用量")

    def save(self):
        self.material.update({k:w.text().strip() for k,w in self.fields.items()}); self.material["item_id"] = self.model.currentData()
        try:
            test = copy.deepcopy(self.order); test["materials"] = [self.material]; validate_order(test)
        except Exception as exc: QMessageBox.warning(self, "请检查", str(exc)); return
        self.accept()


class OrderDialog(QDialog):
    def __init__(self, store, order=None, parent=None):
        super().__init__(parent); self.store = store; self.order = copy.deepcopy(order or new_order()); self.saved = False
        self.setWindowTitle("订单详情" if order else "登记新订单"); self.resize(1040, 770)
        self.setMinimumSize(840, 630)
        root = QVBoxLayout(self); root.setContentsMargins(22, 18, 22, 18)
        root.addWidget(label("订单登记与跟进", "title")); tabs = QTabWidget(); root.addWidget(tabs)
        basic = QWidget(); form = QFormLayout(basic); form.setContentsMargins(22,22,22,22); form.setSpacing(12); self.fields = {}
        for key, title in [("number", "订单号 *"), ("customer", "客户"), ("owner", "订单经办人"), ("delivery_date", "要求交期"),
                           ("contract_no", "合同号"), ("contract_owner", "合同经办人"), ("sales_no", "销售订单号"), ("sales_owner", "销售订单经办人")]:
            w = QLineEdit(self.order.get(key,"")); self.fields[key] = w; form.addRow(title,w)
            if key == "delivery_date": w.setPlaceholderText("YYYY-MM-DD（可留空）")
        self.received = QDateTimeEdit(); self.received.setCalendarPopup(True); self.received.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.received.setDateTime(QDateTime.fromString(self.order["received_at"],Qt.DateFormat.ISODate)); form.addRow("接单时间", self.received)
        self.contract = QCheckBox("合同已录入并确认"); self.contract.setChecked(self.order.get("contract",False)); form.addRow(self.contract)
        form.addRow(label("合同号、销售订单号各自关联到此订单及填写的经办人。", "muted")); tabs.addTab(basic,"基本信息 / 合同")
        items_page = QWidget(); il = QVBoxLayout(items_page); il.setContentsMargins(16,16,16,16)
        il.addWidget(label("整单操作会应用到当前全部型号；双击型号可单独确认或撤销。新增型号需重新确认。", "muted"))
        row = QHBoxLayout()
        for key, title in [("bom","整单 BOM 确认"),("analyzed","整单分析确认"),("packaging","整单包材信息确认"),("completed","整单跟进完成")]:
            row.addWidget(button(title,lambda checked=False,k=key:self.bulk(k)))
        il.addLayout(row)
        self.items = table(["型号","产品数量","BOM","分析","分析日期","包材信息","跟进完成"]); il.addWidget(self.items)
        row = QHBoxLayout(); row.addWidget(button("＋ 添加型号", self.add_item)); row.addWidget(button("编辑所选型号", self.edit_item)); row.addWidget(button("移除所选型号",self.remove_item)); row.addStretch(); il.addLayout(row)
        self.items.cellDoubleClicked.connect(lambda *_:self.edit_item()); tabs.addTab(items_page,"型号与确认项")
        materials_page = QWidget(); ml = QVBoxLayout(materials_page); ml.setContentsMargins(16,16,16,16)
        ml.addWidget(label("按型号登记包材，用量修改后自动重新计算请购数量。不同型号的同名包材分别保留。", "muted"))
        self.materials = table(["型号","包材","单件用量","请购数量","已到数量","交期","提醒日"]); ml.addWidget(self.materials)
        row = QHBoxLayout(); row.addWidget(button("＋ 添加包材",self.add_material)); row.addWidget(button("编辑交期 / 到料",self.edit_material)); row.addWidget(button("移除所选包材",self.remove_material)); row.addStretch(); ml.addLayout(row)
        self.materials.cellDoubleClicked.connect(lambda *_:self.edit_material()); tabs.addTab(materials_page,"包材请购与到料")
        notes_page = QWidget(); nl = QVBoxLayout(notes_page); self.notes = QTextEdit(self.order.get("notes","")); self.notes.setPlaceholderText("记录异常、处理进展或下次跟进事项……"); nl.addWidget(self.notes)
        history = QTextEdit(); history.setReadOnly(True); history.setMaximumHeight(180); history.setPlainText("\n".join(f"{at}  {action}" for at,action in store.history(self.order["id"])))
        nl.addWidget(label("保存历史", "muted")); nl.addWidget(history); tabs.addTab(notes_page,"跟进记录")
        footer = QHBoxLayout(); footer.addWidget(label("修改将在点击“保存订单”后生效。", "muted"),1); footer.addWidget(button("取消",self.reject)); footer.addWidget(button("保存订单",self.save,True)); root.addLayout(footer)
        self.refresh()

    def refresh(self):
        self.items.setRowCount(0)
        for row,item in enumerate(self.order["items"]):
            put(self.items,row,[item["model"],item["quantity"],"已确认" if item["bom"] else "待确认", "已确认" if item["analyzed"] else "待确认", item["analysis_at"],"已确认" if item["packaging"] else "待确认", "完成" if item["completed"] else "进行中"])
        self.materials.setRowCount(0)
        for row,m in enumerate(self.order["materials"]):
            model = next(i["model"] for i in self.order["items"] if i["id"]==m["item_id"])
            put(self.materials,row,[model,m["name"],m["usage"],fmt(demand(self.order,m)),m.get("arrived","0"),m.get("due_date",""),m.get("remind_date") or m.get("due_date","")])

    def bulk(self,key):
        if not self.order["items"]: QMessageBox.information(self,"提示","请先添加型号"); return
        done = all_checked(self.order,key)
        if done:
            if QMessageBox.question(self,"撤销整单确认","此项已全部确认。是否撤销当前全部型号的此项确认？") != QMessageBox.StandardButton.Yes: return
        confirm_all(self.order,key,not done); self.refresh()

    def add_item(self): self.change_item(None)
    def edit_item(self):
        row = self.items.currentRow()
        if row>=0: self.change_item(row)
    def change_item(self,row):
        dialog = ItemDialog(self.order["items"][row] if row is not None else new_item(),self)
        if dialog.exec():
            value = dialog.value(); trial = copy.deepcopy(self.order); trial["number"] = trial["number"] or "校验"
            if row is None: trial["items"].append(value)
            else: trial["items"][row] = value
            try: validate_order(trial)
            except Exception as exc: QMessageBox.warning(self,"无法保存型号",str(exc)); return
            self.order["items"] = trial["items"]; self.refresh()
    def remove_item(self):
        row = self.items.currentRow()
        if row<0:return
        item=self.order["items"][row]
        if any(m["item_id"]==item["id"] for m in self.order["materials"]): QMessageBox.warning(self,"无法移除","此型号有关联包材，请先处理包材记录。"); return
        if QMessageBox.question(self,"移除型号",f"移除 {item['model']}？保存订单后生效。") == QMessageBox.StandardButton.Yes:
            self.order["items"].pop(row); self.refresh()
    def add_material(self): self.change_material(None)
    def edit_material(self):
        row = self.materials.currentRow()
        if row>=0: self.change_material(row)
    def change_material(self,row):
        if not self.order["items"]: QMessageBox.information(self,"提示","请先在“型号与确认项”中添加型号"); return
        trial=copy.deepcopy(self.order); trial["number"]=trial["number"] or "校验"
        dialog=MaterialDialog(trial,self.order["materials"][row] if row is not None else None,self)
        if dialog.exec():
            if row is None:self.order["materials"].append(dialog.material)
            else:self.order["materials"][row]=dialog.material
            self.refresh()
    def remove_material(self):
        row=self.materials.currentRow()
        if row>=0 and QMessageBox.question(self,"移除包材","移除此包材跟进记录？保存订单后生效。") == QMessageBox.StandardButton.Yes:
            self.order["materials"].pop(row); self.refresh()
    def save(self):
        self.order.update({k:w.text().strip() for k,w in self.fields.items()}); self.order["received_at"]=self.received.dateTime().toString(Qt.DateFormat.ISODate)
        self.order["contract"]=self.contract.isChecked(); self.order["notes"]=self.notes.toPlainText()
        try:self.store.save_order(self.order)
        except Exception as exc:
            QMessageBox.warning(self,"保存失败","订单号已存在，请使用其他订单号。" if "UNIQUE" in str(exc) else str(exc)); return
        self.saved=True; self.accept()


class Worker(QThread):
    success=Signal(object); failure=Signal(str); message=Signal(str)
    def __init__(self, fn, parent): super().__init__(parent); self.fn=fn
    def run(self):
        try:self.success.emit(self.fn(self.message.emit))
        except Exception as exc:self.failure.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self,store=None):
        super().__init__(); self.store=store or Store(); self.setWindowTitle(f"{APP_NAME} · v{VERSION}"); self.setWindowIcon(icon()); self.resize(1320,850); self.setMinimumSize(1040,700)
        self.workers=[]; self.quitting=False; self.daily_dirty=False
        central=QWidget(); self.setCentralWidget(central); outer=QHBoxLayout(central); outer.setContentsMargins(0,0,0,0); outer.setSpacing(0)
        self.nav=QListWidget(); self.nav.setObjectName("nav"); self.nav.setFixedWidth(198)
        for title in ["今日待办","订单总表","包材跟进","每日跟进","设置与更新"]:self.nav.addItem(title)
        outer.addWidget(self.nav); self.pages=QStackedWidget(); outer.addWidget(self.pages,1)
        self.dashboard(); self.orders_page(); self.materials_page(); self.daily_page(); self.settings_page()
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex); self.nav.setCurrentRow(0)
        self.statusBar().showMessage("数据保存在本机  ·  自然日规则  ·  包材交期提醒 09:00")
        self.tray=QSystemTrayIcon(icon(),self); self.tray.setToolTip(APP_NAME)
        menu=QMenu(); menu.addAction("打开工作台",self.show_normal); menu.addAction("退出程序",self.exit_app); self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason:self.show_normal() if reason==QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.tray.messageClicked.connect(self.show_normal)
        if QSystemTrayIcon.isSystemTrayAvailable():self.tray.show()
        self.timer=QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(30000)
        self.refresh(); self.load_daily(); QTimer.singleShot(1800,self.tick)

    def page(self,title,subtitle):
        page=QWidget(); layout=QVBoxLayout(page); layout.setContentsMargins(28,25,28,22); layout.setSpacing(16)
        layout.addWidget(label(title,"title")); layout.addWidget(label(subtitle,"muted")); self.pages.addWidget(page); return layout

    def dashboard(self):
        layout=self.page("今日待办","优先处理未完成的确认与交期事项。双击待办可进入订单详情。")
        row=QHBoxLayout(); self.stats=[]
        for title in ["进行中的订单","高优先级订单","待确认包材信息","未解决每日跟进"]:
            frame=QFrame(); frame.setObjectName("card"); box=QVBoxLayout(frame); box.setContentsMargins(18,14,18,14)
            box.addWidget(label(title,"muted")); value=label("0","stat"); box.addWidget(value); self.stats.append(value); row.addWidget(frame)
        layout.addLayout(row); actions=QHBoxLayout(); actions.addWidget(button("＋ 登记新订单",lambda:self.edit_order(),True)); actions.addWidget(button("导入订单",self.import_orders)); actions.addStretch(); layout.addLayout(actions)
        self.todo=table(["优先级","订单号","客户","型号 / 范围","待办事项","经办人"]); layout.addWidget(self.todo)
        self.todo.cellDoubleClicked.connect(lambda row,col:self.open_identity(self.todo,row))
        self.empty=label("暂无待办。登记或导入订单后，未完成事项会自动列在这里。","muted"); layout.addWidget(self.empty)

    def orders_page(self):
        layout=self.page("订单总表","以整单跟进为主，保留每个型号的独立确认。完成的订单仍可查询和重新打开。")
        row=QHBoxLayout(); self.search=QLineEdit(); self.search.setPlaceholderText("搜索订单号、客户、型号、合同 / 销售单号、经办人"); row.addWidget(self.search,1)
        self.filter=QComboBox(); self.filter.addItems(["全部订单","进行中","高优先级","已完成"]); row.addWidget(self.filter)
        row.addWidget(button("＋ 新订单",lambda:self.edit_order(),True)); row.addWidget(button("导入",self.import_orders)); row.addWidget(button("导入模板",self.template)); layout.addLayout(row)
        self.orders_table=table(["优先级","订单号","客户","经办人","型号数","合同","BOM","分析","包材信息","跟进完成"]); layout.addWidget(self.orders_table)
        self.orders_table.cellDoubleClicked.connect(lambda row,col:self.open_identity(self.orders_table,row)); self.search.textChanged.connect(self.refresh); self.filter.currentIndexChanged.connect(self.refresh)
        row=QHBoxLayout(); row.addWidget(button("打开所选订单",lambda:self.open_identity(self.orders_table,self.orders_table.currentRow()))); row.addStretch(); self.order_count=label("","muted"); row.addWidget(self.order_count); layout.addLayout(row)

    def materials_page(self):
        layout=self.page("包材跟进","请购数量按产品数量 × 单件用量计算。双击记录可进入订单，更新交期、到料及备注。")
        self.material_filter=QComboBox(); self.material_filter.addItems(["全部包材","未到齐","已到齐"]); self.material_filter.currentIndexChanged.connect(self.refresh); layout.addWidget(self.material_filter)
        self.material_table=table(["订单号","型号","包材","请购数量","单位","已到","未到","预计交期","提醒日 09:00","请购单号"]); layout.addWidget(self.material_table)
        self.material_table.cellDoubleClicked.connect(lambda row,col:self.open_identity(self.material_table,row))

    def daily_page(self):
        layout=self.page("每日跟进","数据在其他系统刷新；这里只记录检查结果、是否需要跟进及处理进展。历史未解决事项会持续出现在今日待办中。")
        row=QHBoxLayout(); row.addWidget(label("记录日期")); self.daily_date=date_field(); self.daily_date.dateChanged.connect(self.date_changed); row.addWidget(self.daily_date); row.addStretch(); row.addWidget(button("保存当日记录",self.save_daily,True)); layout.addLayout(row)
        self.daily_widgets={}
        for key in ["分仓数据","成品入库数据","销售出库数据"]:
            frame=QFrame(); frame.setObjectName("card"); box=QVBoxLayout(frame); box.setContentsMargins(18,14,18,14)
            header=QHBoxLayout(); header.addWidget(label(key)); state=QComboBox(); state.addItems(["待检查","无需跟进","需要跟进","已处理"]); header.addWidget(state); header.addStretch(); box.addLayout(header)
            notes=QLineEdit(); notes.setPlaceholderText("关联订单、经办人、异常情况与处理进展……"); box.addWidget(notes); layout.addWidget(frame); self.daily_widgets[key]=(state,notes)
            state.currentIndexChanged.connect(self.autosave_daily); notes.editingFinished.connect(self.autosave_daily)
        layout.addWidget(label("状态和备注修改后自动保存；也可点击“保存当日记录”。切换日期可继续处理历史事项。","muted")); layout.addStretch()
        self.current_daily_day=date.today().isoformat(); self.loading_daily=False

    def settings_page(self):
        layout=self.page("设置与更新",f"{APP_NAME}  v{VERSION}  ·  Windows 桌面版")
        frame=QFrame(); frame.setObjectName("card"); box=QVBoxLayout(frame); box.setContentsMargins(22,18,22,18)
        box.addWidget(label("提醒规则")); box.addWidget(label("• 合同：接单满 24 小时仍未确认，提高优先级。\n• 包材信息：分析日期满 10 个自然日仍未确认，提高优先级。\n• 包材交期：填写的提醒日 09:00 起提示，未填写提醒日时使用交期。\n• 整单跟进完成后停止该单提醒；单个型号完成后停止该型号包材提醒。"))
        self.tray_check=QCheckBox("关闭窗口后保留在系统托盘，继续提醒"); self.tray_check.setChecked(self.store.get("tray","1")=="1"); self.tray_check.toggled.connect(lambda value:self.store.set("tray","1" if value else "0")); box.addWidget(self.tray_check)
        self.startup=QCheckBox("登录 Windows 后自动启动（最小化到托盘）"); self.startup.setChecked(self.startup_enabled()); self.startup.toggled.connect(self.change_startup); box.addWidget(self.startup)
        box.addWidget(label("准点提醒需要程序正在运行且电脑已开机。若 09:00 时未运行，打开后会补查；优先级仍会按期限计算。","muted")); layout.addWidget(frame)
        row=QHBoxLayout(); row.addWidget(button("导出数据备份",self.export_backup)); row.addWidget(button("从备份恢复",self.restore_backup)); row.addWidget(button("打开数据目录",lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir()))))); row.addStretch(); layout.addLayout(row)
        row=QHBoxLayout(); self.update_button=button("检查新版本",self.check_update,True); row.addWidget(self.update_button); row.addWidget(button("打开 GitHub 项目",lambda:QDesktopServices.openUrl(QUrl(f"https://github.com/{REPOSITORY}")))); row.addStretch(); layout.addLayout(row)
        self.update_status=label("更新会校验下载文件，自动备份数据库，再替换程序并重启。","muted"); layout.addWidget(self.update_status); layout.addStretch()

    def refresh(self,*args):
        if not hasattr(self,"material_table"):return
        orders=self.store.orders()
        orders.sort(key=lambda o:(all_checked(o,"completed"),-max((r["level"] for r in reminders(o)),default=0)))
        self.by_id={o["id"]:o for o in orders}; self.todo.setRowCount(0); self.orders_table.setRowCount(0); self.material_table.setRowCount(0)
        tasks=[]; elevated=0; waiting=0; active=0
        for order in orders:
            due=reminders(order); completed=all_checked(order,"completed"); rank=max([r["level"] for r in due],default=0)
            active+=not completed; elevated+=bool(rank); waiting+=sum(i["analyzed"] and not i["packaging"] and not i["completed"] for i in order["items"])
            priority="已完成" if completed else ("紧急" if rank==3 else "高" if rank==2 else "正常")
            keyword=self.search.text().strip().lower(); searchable=" ".join(str(order.get(k,"")) for k in ["number","customer","owner","contract_no","contract_owner","sales_no","sales_owner"])+" "+" ".join(i["model"] for i in order["items"])
            filter_index=self.filter.currentIndex(); visible=(not keyword or keyword in searchable.lower()) and (filter_index==0 or filter_index==1 and not completed or filter_index==2 and rank>0 or filter_index==3 and completed)
            if visible:put(self.orders_table,self.orders_table.rowCount(),[priority,order["number"],order["customer"],order["owner"],len(order["items"]),"已确认" if order["contract"] else "待确认",progress(order,"bom"),progress(order,"analyzed"),progress(order,"packaging"),progress(order,"completed")],order["id"])
            for reminder in due:
                tasks.append((reminder["level"],order["number"],order["customer"],reminder["model"],reminder["reason"],order.get("contract_owner") or order["owner"] if reminder["kind"]=="contract" else order["owner"],order["id"]))
            if not completed:
                if not order["contract"] and not any(r["kind"]=="contract" for r in due):tasks.append((0,order["number"],order["customer"],"整单","待确认合同录入",order.get("contract_owner") or order["owner"],order["id"]))
                for key,title in [("bom","待确认工程 BOM"),("analyzed","待确认分析")]:
                    missing=[i["model"] for i in order["items"] if not i[key] and not i["completed"]]
                    if missing:tasks.append((0,order["number"],order["customer"],"、".join(missing),title,order["owner"],order["id"]))
            for m in order["materials"]:
                qty=demand(order,m); arrived=updater_decimal(m.get("arrived",0)); missing=max(0,qty-arrived); mf=self.material_filter.currentIndex()
                if mf==1 and missing<=0 or mf==2 and missing>0:continue
                model=next(i["model"] for i in order["items"] if i["id"]==m["item_id"])
                put(self.material_table,self.material_table.rowCount(),[order["number"],model,m["name"],fmt(qty),m.get("unit","个"),fmt(arrived),fmt(missing),m.get("due_date",""),m.get("remind_date") or m.get("due_date",""),m.get("request_no","")],order["id"])
        daily_pending=0
        for day, records in self.store.daily_all():
            for key,record in records.items():
                if record.get("state")=="需要跟进":
                    daily_pending+=1; tasks.append((1,"每日记录",day,key,record.get("notes") or "需要跟进","",f"daily:{day}"))
        for rank,no,customer,model,reason,owner,identity in sorted(tasks,key=lambda x:-x[0]):
            row=self.todo.rowCount(); put(self.todo,row,["紧急" if rank==3 else "高" if rank==2 else "待跟进" if rank==1 else "正常",no,customer,model,reason,owner],identity)
            if rank>=2:self.todo.item(row,0).setForeground(QColor("#be4343" if rank==3 else "#b86c15"))
        for w,value in zip(self.stats,[active,elevated,waiting,daily_pending]):w.setText(str(value))
        self.empty.setVisible(not tasks); self.order_count.setText(f"当前显示 {self.orders_table.rowCount()} 单 / 共 {len(orders)} 单")

    def open_identity(self,t,row):
        if row<0:return
        identity=t.item(row,0).data(Qt.ItemDataRole.UserRole)
        if identity.startswith("daily:"):
            self.daily_date.setDate(QDate.fromString(identity[6:],"yyyy-MM-dd")); self.nav.setCurrentRow(3)
        else:self.edit_order(self.by_id.get(identity))
    def edit_order(self,order=None):
        dialog=OrderDialog(self.store,order,self)
        if dialog.exec():self.refresh()
    def template(self):
        path,_=QFileDialog.getSaveFileName(self,"保存导入模板","订单导入模板.xlsx","Excel (*.xlsx);;CSV (*.csv)")
        if path:
            try:write_template(path); QMessageBox.information(self,"模板已保存","订单号、型号、产品数量必填。同一订单可分多行填写不同型号。示例行请替换后再导入。")
            except Exception as exc:QMessageBox.warning(self,"保存失败",str(exc))
    def import_orders(self):
        path,_=QFileDialog.getOpenFileName(self,"导入新订单","","订单文件 (*.xlsx *.csv)")
        if not path:return
        try:orders=read_import(path,[o["number"] for o in self.store.orders()])
        except Exception as exc:QMessageBox.warning(self,"导入检查",str(exc));return
        dialog=QDialog(self);dialog.setWindowTitle("导入预览");dialog.resize(860,520);box=QVBoxLayout(dialog)
        box.addWidget(label(f"将新增 {len(orders)} 个订单、{sum(len(o['items']) for o in orders)} 个型号。确认后统一保存。"))
        preview=table(["订单号","客户","经办人","型号","数量"])
        for o in orders:
            for i in o["items"]:put(preview,preview.rowCount(),[o["number"],o["customer"],o["owner"],i["model"],i["quantity"]])
        box.addWidget(preview);buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);box.addWidget(buttons)
        if dialog.exec():
            try:self.store.save_orders(orders);self.refresh();QMessageBox.information(self,"导入完成",f"已新增 {len(orders)} 个订单。")
            except Exception as exc:QMessageBox.warning(self,"导入失败",str(exc))
    def date_changed(self,*args):
        if not hasattr(self,"current_daily_day"):return
        self.save_daily(silent=True);self.load_daily()
    def load_daily(self):
        self.loading_daily=True;self.current_daily_day=self.daily_date.date().toString("yyyy-MM-dd");records=self.store.daily(self.current_daily_day)
        for key,(state,notes) in self.daily_widgets.items():
            state.setCurrentText(records.get(key,{}).get("state","待检查"));notes.setText(records.get(key,{}).get("notes",""))
        self.loading_daily=False
    def autosave_daily(self,*args):
        if not getattr(self,"loading_daily",True):self.save_daily(silent=True)
    def save_daily(self,checked=False,silent=False):
        if getattr(self,"loading_daily",False):return
        payload={key:dict(state=state.currentText(),notes=notes.text(),updated_at=datetime.now().isoformat(timespec="seconds")) for key,(state,notes) in self.daily_widgets.items()}
        try:self.store.save_daily(self.current_daily_day,payload);self.refresh()
        except Exception as exc:QMessageBox.warning(self,"保存失败",str(exc));return
        if not silent:self.statusBar().showMessage(f"已保存 {self.current_daily_day} 的跟进记录",5000)
    def tick(self):
        self.refresh();now=datetime.now();due=[(o,reminders(o,now)) for o in self.store.orders()];due=[(o,r) for o,r in due if r]
        key=now.date().isoformat()+":"+"|".join(sorted(o["id"]+str(len(r)) for o,r in due))
        if now.hour>=9 and due and self.store.get("notified")!=key:
            self.tray.showMessage(APP_NAME,f"{len(due)} 个订单有高优先级事项，请打开工作台查看。",QSystemTrayIcon.MessageIcon.Information,10000);self.store.set("notified",key)
    def export_backup(self):
        path,_=QFileDialog.getSaveFileName(self,"导出数据备份",f"订单工作台备份-{date.today()}.json","备份 (*.json)")
        if path:
            try:self.store.export_json(path);QMessageBox.information(self,"备份完成","全部订单、包材、每日记录和保存历史已导出。")
            except Exception as exc:QMessageBox.warning(self,"备份失败",str(exc))
    def restore_backup(self):
        path,_=QFileDialog.getOpenFileName(self,"选择数据备份","","备份 (*.json)")
        if path and QMessageBox.question(self,"恢复备份","恢复会替换当前数据。程序会先自动备份现有数据库，是否继续？")==QMessageBox.StandardButton.Yes:
            try:backup=self.store.restore_json(path);self.load_daily();self.refresh();QMessageBox.information(self,"恢复完成",f"恢复成功。替换前的数据备份在：\n{backup}")
            except Exception as exc:QMessageBox.warning(self,"恢复失败",str(exc))
    def startup_enabled(self):
        if sys.platform!="win32":return False
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r"Software\Microsoft\Windows\CurrentVersion\Run") as key:return bool(winreg.QueryValueEx(key,"OrderFollowupDesktop")[0])
        except OSError:return False
    def change_startup(self,enabled):
        try:
            if not getattr(sys,"frozen",False):raise ValueError("请在打包后的 Windows 程序中设置开机启动")
            import winreg
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                if enabled:winreg.SetValueEx(key,"OrderFollowupDesktop",0,winreg.REG_SZ,f'"{sys.executable}" --minimized')
                else:
                    try:winreg.DeleteValue(key,"OrderFollowupDesktop")
                    except FileNotFoundError:pass
        except Exception as exc:
            self.startup.blockSignals(True);self.startup.setChecked(self.startup_enabled());self.startup.blockSignals(False);QMessageBox.warning(self,"设置未完成",str(exc))
    def run_worker(self,fn,success):
        w=Worker(fn,self);self.workers.append(w);w.message.connect(self.update_status.setText);w.success.connect(success);w.failure.connect(self.update_error);w.finished.connect(lambda:self.workers.remove(w));w.start()
    def check_update(self):
        self.update_button.setEnabled(False);self.update_status.setText("正在查询 GitHub 最新版本……");self.run_worker(lambda _:updater.get_release(),self.release_ready)
    def update_error(self,message):
        self.update_button.setEnabled(True);self.update_status.setText("更新未完成："+message)
    def release_ready(self,release):
        self.update_button.setEnabled(True)
        if updater.version_tuple(release["tag_name"])<=updater.version_tuple(VERSION):self.update_status.setText(f"当前 v{VERSION} 已是最新版本。");return
        if not getattr(sys,"frozen",False):self.update_status.setText("开发模式：发现 "+release["tag_name"]+"，请在 Windows 程序中更新。");return
        if QMessageBox.question(self,"发现新版本",f"当前 v{VERSION} → {release['tag_name']}\n下载、备份数据并重启更新？")!=QMessageBox.StandardButton.Yes:return
        self.update_button.setEnabled(False);self.run_worker(lambda emit:updater.download_release(release,emit),self.download_ready)
    def download_ready(self,path):
        try:self.store.backup();updater.launch_replacement(path)
        except Exception as exc:self.update_error(str(exc));return
        self.quitting=True;QTimer.singleShot(300,self.exit_app)
    def show_normal(self):self.showNormal();self.raise_();self.activateWindow()
    def closeEvent(self,event):
        self.save_daily(silent=True)
        if not self.quitting and self.tray_check.isChecked() and self.tray.isVisible():self.hide();event.ignore();return
        if self.workers:event.ignore();QMessageBox.information(self,"正在更新","请等待版本查询或下载结束后退出。");return
        event.accept();self.tray.hide()
    def exit_app(self):
        if self.workers:QTimer.singleShot(500,self.exit_app);return
        self.quitting=True;self.save_daily(silent=True);self.tray.hide();QApplication.instance().quit()


def updater_decimal(value):
    from decimal import Decimal
    return Decimal(str(value))
