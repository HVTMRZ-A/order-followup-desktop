import copy
import re
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import QDate, QDateTime, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QCursor, QDesktopServices, QFontMetrics, QIcon
from PySide6.QtWidgets import (QAbstractItemView, QAbstractSpinBox, QApplication, QCheckBox, QComboBox,
                               QDateEdit, QDateTimeEdit, QDialog, QFileDialog,
                               QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu,
                               QMessageBox, QPushButton, QStackedWidget, QSystemTrayIcon, QTableWidget,
                               QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget)

from . import APP_NAME, REPOSITORY, VERSION, updater
from .domain import (all_checked, confirm_all, demand, fmt, new_item, new_order, progress,
                     reminders, uid, validate_order)
from .importer import read_any, read_import, write_template
from .production import (HOME_COLUMNS, PACKAGING_COLUMNS, PARTS_COLUMNS, PLAN_COLUMNS,
                        export_plan_book, home_rows, next_serial, packaging_rows, parts_rows,
                        plan_rows, read_plan_serials)
from .storage import Store, data_dir
from .theme import (ACCENT, DANGER, FAINT, INK, INK_SOFT, LINE, MUTED, STYLE, SUCCESS, WARN,
                    BadgeDelegate, ProgressDelegate, StatusDelegate, app_icon, brand_mark, icon, pixmap)

NAV = [("今日待办", "dashboard"), ("订单总表", "orders"), ("包材跟进", "package"),
       ("每日跟进", "daily"), ("设置与更新", "gear")]

# 订单总表 = 计划总表 38 列（与「最新」表一致）+ 前置优先级、尾部跟进状态
ORDERS_HEADERS = ["优先级"] + PLAN_COLUMNS + ["跟进"]
ORDERS_WIDTHS = [82, 92, 72, 62, 108, 136, 96, 260, 96, 64, 64, 64, 58, 68, 56, 56, 72, 92, 92, 92, 92,
                 64, 92, 86, 92, 62, 66, 96, 104, 104, 104, 240, 66, 66, 66, 66, 66, 66, 76, 168]
ORDERS_DATE_COLUMNS = ("接单日期", "客户交期", "生产单交期", "受订日期", "分析时间", "派工日期",
                       "总装生产时间", "包材资料下发日期", "包材采购时间")
ORDERS_RIGHT_COLUMNS = tuple(range(9, 17)) + (25,)

# 订单总表页的四个视图，对应计划总表的四张 sheet
PARTS_WIDTHS = [72, 90, 100, 116, 96, 110, 300, 100, 80, 72, 70, 150]
PARTS_RIGHT = (8, 9)
HOME_WIDTHS = [92, 96, 116, 150, 110, 300, 66, 96, 78, 70, 180]
HOME_RIGHT = (6, 8)
PACKAGING_WIDTHS = [116, 150, 120, 300, 80, 104, 96, 104, 180]


# ------------------------------------------------------------------ 基础控件
def label(text, name=None, wrap=True):
    widget = QLabel(text)
    widget.setWordWrap(wrap)
    if name:
        widget.setObjectName(name)
    return widget


def button(text, callback, kind=None, icon_name=None, tint=None):
    widget = QPushButton(text)
    if kind:
        widget.setObjectName(kind)
    if icon_name:
        color = tint or ("#ffffff" if kind == "primary" else INK_SOFT)
        widget.setIcon(icon(icon_name, color, 15))
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.clicked.connect(callback)
    return widget


def ghost_row(*widgets, gap=8, stretch=True):
    layout = QHBoxLayout()
    layout.setSpacing(gap)
    for widget in widgets:
        layout.addWidget(widget)
    if stretch:
        layout.addStretch(1)
    return layout


def dialog_footer(on_cancel, on_confirm, confirm_text="保存"):
    """对话框底部：左下提示 + 右侧「取消 / 保存」。"""
    row = QHBoxLayout()
    row.setSpacing(8)
    row.addStretch(1)
    cancel = button("取消", on_cancel)
    confirm = button(confirm_text, on_confirm, "primary")
    for item in (cancel, confirm):
        item.setMinimumWidth(86)
        row.addWidget(item)
    return row


def panel(table_widget, title="", meta=""):
    """把表格包进卡片，带可选的小标题和右侧说明。"""
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(6, 0, 6, 8)
    layout.setSpacing(0)
    meta_label = None
    if title:
        header = QHBoxLayout()
        header.setContentsMargins(14, 13, 10, 8)
        header.setSpacing(8)
        header.addWidget(label(title, "section", False))
        header.addStretch(1)
        meta_label = label(meta, "meta", False)
        header.addWidget(meta_label)
        layout.addLayout(header)
    layout.addWidget(table_widget, 1)
    return frame, meta_label


def shadow(widget, blur=24, dy=3, alpha=24):
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, dy)
    effect.setColor(QColor(23, 43, 77, alpha))
    widget.setGraphicsEffect(effect)


def chip(icon_name, tint, background, size=38):
    holder = QLabel()
    holder.setFixedSize(size, size)
    holder.setAlignment(Qt.AlignmentFlag.AlignCenter)
    holder.setStyleSheet(f"background:{background}; border-radius:{size // 3}px;")
    holder.setPixmap(pixmap(icon_name, tint, int(size * 0.52)))
    return holder


def field_row(layout, entries, gap=18):
    line = QHBoxLayout()
    line.setSpacing(gap)
    for entry in entries:
        if entry is None:
            line.addStretch(1)
            continue
        title, widget = entry
        box = QVBoxLayout()
        box.setSpacing(6)
        box.addWidget(label(title, "fieldLabel", False))
        box.addWidget(widget)
        line.addLayout(box, 1)
    layout.addLayout(line)
    return line


def table(headers, widths=None, stretch=None, height=40, right=()):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setAlternatingRowColors(False)
    widget.setShowGrid(True)
    widget.setWordWrap(False)
    widget.setFrameShape(QFrame.Shape.NoFrame)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    widget.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    widget.verticalHeader().hide()
    widget.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
    widget.verticalHeader().setDefaultSectionSize(height)
    header = widget.horizontalHeader()
    header.setHighlightSections(False)
    header.setStretchLastSection(False)
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    header.setFixedHeight(36)
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    if widths:
        for column, width in enumerate(widths):
            if width:
                header.resizeSection(column, width)
    if stretch is not None:
        header.setSectionResizeMode(stretch, QHeaderView.ResizeMode.Stretch)
    for column in right:
        item = widget.horizontalHeaderItem(column)
        if item is not None:
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    widget.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
    return widget


def put(widget, row, values, identity=None):
    widget.insertRow(row)
    for column, value in enumerate(values):
        item = QTableWidgetItem(str(value))
        item.setToolTip(str(value))
        item.setData(Qt.ItemDataRole.UserRole, identity)
        widget.setItem(row, column, item)


def align_numbers(widget, row, columns):
    for column in columns:
        item = widget.item(row, column)
        if item is not None:
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


def fit_headers(widget, headers):
    """按表头字体实际宽度抬高列宽下限，避免「电压(V)」之类被裁成「电压(」。"""
    font = widget.horizontalHeader().font()
    font.setBold(True)
    metrics = QFontMetrics(font)
    for column, text in enumerate(headers):
        need = metrics.horizontalAdvance(text) + 22
        if widget.columnWidth(column) < need:
            widget.setColumnWidth(column, need)


def date_field(value="", optional=False):
    if optional:
        widget = QLineEdit(value)
        widget.setPlaceholderText("YYYY-MM-DD（可留空）")
        return widget
    widget = QDateEdit()
    widget.setCalendarPopup(True)
    widget.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    widget.setDisplayFormat("yyyy-MM-dd")
    widget.setDate(QDate.fromString(value, "yyyy-MM-dd") if value else QDate.currentDate())
    return widget


def rule_row(text):
    layout = QHBoxLayout()
    layout.setSpacing(9)
    dot = QLabel()
    dot.setFixedSize(16, 16)
    dot.setPixmap(pixmap("check", ACCENT, 13, 2.4))
    layout.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
    layout.addWidget(label(text, "muted"), 1)
    return layout


# ------------------------------------------------------------------ 对话框
class ItemDialog(QDialog):
    def __init__(self, item, parent):
        super().__init__(parent)
        self.setWindowTitle("型号与确认项")
        self.resize(520, 420)
        self.setMinimumWidth(480)
        self.item = copy.deepcopy(item)
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 20)
        root.setSpacing(0)
        root.addWidget(label("型号与确认项", "dialogTitle", False))
        root.addSpacing(5)
        root.addWidget(label("勾选会立即改变待办与优先级；分析日期用于计算包材信息的 10 天期限。", "hint"))
        root.addSpacing(18)

        self.model = QLineEdit(item["model"])
        self.model.setPlaceholderText("例如 LF3000-A")
        self.qty = QLineEdit(item["quantity"])
        field_row(root, [("产品型号 *", self.model), ("产品数量 *", self.qty)])
        root.addSpacing(14)

        self.flags = {}
        flags_grid = QHBoxLayout()
        flags_grid.setSpacing(18)
        left = QVBoxLayout()
        left.setSpacing(10)
        right_box = QVBoxLayout()
        right_box.setSpacing(10)
        for index, (key, title) in enumerate([("bom", "工程 BOM 已匹配"), ("analyzed", "分析已完成"),
                                              ("packaging", "包材信息已确认"), ("completed", "该型号跟进完成")]):
            box = QCheckBox(title)
            box.setChecked(item.get(key, False))
            (left if index % 2 == 0 else right_box).addWidget(box)
            self.flags[key] = box
        flags_grid.addLayout(left, 1)
        flags_grid.addLayout(right_box, 1)
        root.addLayout(flags_grid)
        root.addSpacing(16)

        self.analysis_date = date_field(item.get("analysis_at", ""))
        field_row(root, [("分析日期", self.analysis_date), None])
        root.addSpacing(8)
        root.addWidget(label("勾选“分析已完成”后，包材信息的 10 天期限从该日期开始计算。", "hint"))
        root.addStretch(1)
        root.addLayout(dialog_footer(self.reject, self.accept, "保存型号"))

    def value(self):
        self.item.update(model=self.model.text().strip(), quantity=self.qty.text().strip())
        self.item.update({key: widget.isChecked() for key, widget in self.flags.items()})
        self.item["analysis_at"] = self.analysis_date.date().toString("yyyy-MM-dd") if self.item["analyzed"] else ""
        return self.item


class MaterialDialog(QDialog):
    def __init__(self, order, material, parent):
        super().__init__(parent)
        self.setWindowTitle("包材请购与到料")
        self.resize(680, 640)
        self.setMinimumWidth(620)
        self.order = order
        self.material = copy.deepcopy(material or dict(id=uid(), name="", usage="1", arrived="0"))
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 20)
        root.setSpacing(0)
        root.addWidget(label("包材请购与到料", "dialogTitle", False))
        root.addSpacing(5)
        root.addWidget(label("请购数量按产品数量 × 单件用量自动计算，不扣库存。", "hint"))
        root.addSpacing(18)

        self.model = QComboBox()
        for item in order["items"]:
            self.model.addItem(f"{item['model']}（产品数量 {item['quantity']}）", item["id"])
        self.model.setCurrentIndex(max(0, self.model.findData(self.material.get("item_id"))))

        self.fields = {}
        specs = [("name", "包材名称 *", "", None), ("usage", "单个产品使用量 *", "1", None),
                 ("unit", "计量单位", "个", None), ("request_no", "请购单号", "", None),
                 ("request_date", "请购日期", "", "YYYY-MM-DD"), ("buyer", "采购经办人", "", None),
                 ("due_date", "预计到料日期", "", "YYYY-MM-DD"), ("remind_date", "提醒日期（09:00）", "", "YYYY-MM-DD"),
                 ("arrived", "累计已到数量", "0", None), ("arrival_date", "最近实际到料日期", "", "YYYY-MM-DD")]
        for key, title, default, placeholder in specs:
            widget = QLineEdit(str(self.material.get(key, default)))
            if placeholder:
                widget.setPlaceholderText("YYYY-MM-DD（可留空）")
            self.fields[key] = widget

        field_row(root, [("关联型号", self.model), ("包材名称 *", self.fields["name"])])
        root.addSpacing(14)
        field_row(root, [("单个产品使用量 *", self.fields["usage"]), ("计量单位", self.fields["unit"])])
        root.addSpacing(14)
        field_row(root, [("请购单号", self.fields["request_no"]), ("请购日期", self.fields["request_date"])])
        root.addSpacing(14)
        field_row(root, [("采购经办人", self.fields["buyer"]), ("预计到料日期", self.fields["due_date"])])
        root.addSpacing(14)
        field_row(root, [("提醒日期（09:00）", self.fields["remind_date"]), ("累计已到数量", self.fields["arrived"])])
        root.addSpacing(14)
        field_row(root, [("最近实际到料日期", self.fields["arrival_date"]), None])
        root.addSpacing(14)

        self.calculation = label("")
        calc_box = QFrame()
        calc_box.setObjectName("inner")
        calc_layout = QHBoxLayout(calc_box)
        calc_layout.setContentsMargins(14, 11, 14, 11)
        calc_layout.addWidget(chip("package", ACCENT, "#eaf1fe", 30))
        calc_layout.addWidget(self.calculation, 1)
        root.addWidget(calc_box)

        root.addSpacing(14)
        notes = self.fields.setdefault("notes", QLineEdit(str(self.material.get("notes", ""))))
        notes.setPlaceholderText("跟进记录 / 备注：异常、承诺时间、联系人……")
        field_row(root, [("跟进记录 / 备注", notes)])
        root.addSpacing(10)
        root.addWidget(label("提醒日期留空时使用预计到料日期；到齐后自动停止该包材提醒。", "hint"))
        root.addStretch(1)

        self.model.currentIndexChanged.connect(self.calculate)
        self.fields["usage"].textChanged.connect(self.calculate)
        self.calculate()
        root.addLayout(dialog_footer(self.reject, self.save))

    def calculate(self):
        try:
            material = dict(item_id=self.model.currentData(), usage=self.fields["usage"].text())
            quantity = demand(self.order, material)
            self.calculation.setText(f"本型号所需请购数量：<b>{fmt(quantity)}</b> {self.fields['unit'].text().strip()}")
        except Exception:
            self.calculation.setText("请填写有效的单件用量")

    def save(self):
        self.material.update({key: widget.text().strip() for key, widget in self.fields.items()})
        self.material["item_id"] = self.model.currentData()
        try:
            test = copy.deepcopy(self.order)
            test["materials"] = [self.material]
            validate_order(test)
        except Exception as exc:
            QMessageBox.warning(self, "请检查", str(exc))
            return
        self.accept()


class OrderDialog(QDialog):
    def __init__(self, store, order=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.order = copy.deepcopy(order or new_order())
        self.saved = False
        self.setWindowTitle("订单详情" if order else "登记新订单")
        self.resize(1040, 720)
        self.setMinimumSize(880, 650)

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 18)
        root.setSpacing(0)
        root.addWidget(label("订单登记与跟进" if order else "登记新订单", "dialogTitle", False))
        root.addSpacing(5)
        root.addWidget(label("整单确认会应用到当前全部型号；新增型号不继承先前确认。", "hint"))
        root.addSpacing(14)

        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.tabBar().setExpanding(False)
        tabs.tabBar().setDrawBase(False)
        root.addWidget(tabs, 1)

        # ---- 基本信息 / 合同
        basic = QWidget()
        form = QVBoxLayout(basic)
        form.setContentsMargins(22, 20, 22, 20)
        form.setSpacing(14)
        self.fields = {}
        for key, title, placeholder in [("number", "订单号 *", "例如 SO-2026-001"), ("customer", "客户", ""),
                                        ("customer_no", "客户编号", "生产单上的客订编号，如 D299"),
                                        ("owner", "订单经办人", ""), ("delivery_date", "要求交期", "YYYY-MM-DD（可留空）"),
                                        ("transport", "运输方式", "例如 1*40HQ"),
                                        ("attribute", "订单属性", "例如 新增 / 返单"),
                                        ("plan_serial", "计划序列号", "如 X2601352"),
                                        ("contract_no", "合同号", ""), ("contract_owner", "合同经办人", ""),
                                        ("sales_no", "销售订单号", ""), ("sales_owner", "销售订单经办人", "")]:
            widget = QLineEdit(self.order.get(key, ""))
            if placeholder:
                widget.setPlaceholderText(placeholder)
            self.fields[key] = widget
        field_row(form, [("订单号 *", self.fields["number"]), ("客户", self.fields["customer"])])
        field_row(form, [("客户编号", self.fields["customer_no"]), ("订单经办人", self.fields["owner"]),
                         ("计划序列号", self.fields["plan_serial"])])
        field_row(form, [("运输方式", self.fields["transport"]), ("订单属性", self.fields["attribute"]),
                         ("要求交期", self.fields["delivery_date"])])
        field_row(form, [("合同号", self.fields["contract_no"]), ("合同经办人", self.fields["contract_owner"]),
                         ("销售订单号", self.fields["sales_no"]), ("销售订单经办人", self.fields["sales_owner"])])

        self.received = QDateTimeEdit()
        self.received.setCalendarPopup(True)
        self.received.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.received.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.received.setDateTime(QDateTime.fromString(self.order["received_at"], Qt.DateFormat.ISODate))
        field_row(form, [("接单时间", self.received), None])

        contract_box = QFrame()
        contract_box.setObjectName("inner")
        contract_layout = QHBoxLayout(contract_box)
        contract_layout.setContentsMargins(14, 10, 14, 10)
        self.contract = QCheckBox("合同已录入并确认")
        self.contract.setChecked(self.order.get("contract", False))
        contract_layout.addWidget(self.contract)
        contract_layout.addStretch(1)
        contract_layout.addWidget(label("接单满 24 小时未确认将提升优先级", "hint", False))
        form.addWidget(contract_box)
        form.addWidget(label("合同号、销售订单号各自关联到此订单及填写的经办人。", "hint"))
        form.addStretch(1)
        tabs.addTab(basic, "基本信息 / 合同")

        # ---- 型号与确认项
        items_page = QWidget()
        items_layout = QVBoxLayout(items_page)
        items_layout.setContentsMargins(22, 20, 22, 20)
        items_layout.setSpacing(12)
        bulk = QHBoxLayout()
        bulk.setSpacing(8)
        for key, title in [("bom", "整单 BOM"), ("analyzed", "整单分析"), ("packaging", "整单包材"), ("completed", "整单完成")]:
            bulk.addWidget(button(title, lambda checked=False, k=key: self.bulk(k), "tool"))
        bulk.addStretch(1)
        bulk.addWidget(label("整单操作应用到全部型号", "hint", False))
        items_layout.addLayout(bulk)
        self.items = table(["型号", "产品数量", "BOM", "分析", "分析日期", "包材信息", "跟进完成"],
                           widths=[200, 104, 96, 96, 124, 112, 108], stretch=0, right=(1,))
        for column in (2, 3, 5, 6):
            self.items.setItemDelegateForColumn(column, StatusDelegate(self.items))
        items_frame, _ = panel(self.items, "型号明细", "双击型号单独编辑")
        items_layout.addWidget(items_frame, 1)
        items_layout.addLayout(ghost_row(button("添加型号", self.add_item, "primary", "plus"),
                                         button("编辑所选型号", self.edit_item),
                                         button("移除所选型号", self.remove_item, "danger")))
        self.items.cellDoubleClicked.connect(lambda *_: self.edit_item())
        tabs.addTab(items_page, "型号与确认项")

        # ---- 包材
        materials_page = QWidget()
        materials_layout = QVBoxLayout(materials_page)
        materials_layout.setContentsMargins(22, 20, 22, 20)
        materials_layout.setSpacing(12)
        materials_layout.addWidget(label("按型号登记包材，修改用量后请购数量自动重算；不同型号的同名包材分别保留。", "hint"))
        self.materials = table(["型号", "包材", "单件用量", "请购数量", "已到数量", "交期", "提醒日"],
                               widths=[190, 0, 96, 104, 96, 110, 110], stretch=1, right=(2, 3, 4))
        materials_frame, _ = panel(self.materials, "包材明细", "双击记录编辑交期与到料")
        materials_layout.addWidget(materials_frame, 1)
        materials_layout.addLayout(ghost_row(button("添加包材", self.add_material, "primary", "plus"),
                                             button("编辑交期 / 到料", self.edit_material),
                                             button("移除所选包材", self.remove_material, "danger")))
        self.materials.cellDoubleClicked.connect(lambda *_: self.edit_material())
        tabs.addTab(materials_page, "包材请购与到料")

        # ---- 跟进记录
        notes_page = QWidget()
        notes_layout = QVBoxLayout(notes_page)
        notes_layout.setContentsMargins(22, 20, 22, 20)
        notes_layout.setSpacing(12)
        self.notes = QTextEdit(self.order.get("notes", ""))
        self.notes.setPlaceholderText("记录异常、处理进展或下次跟进事项……")
        notes_layout.addWidget(self.notes, 1)
        notes_layout.addWidget(label("保存历史", "section", False))
        history = QTextEdit()
        history.setReadOnly(True)
        history.setMaximumHeight(170)
        history.setPlainText("\n".join(f"{at.replace('T', ' ')}    {action}" for at, action in store.history(self.order["id"])))
        notes_layout.addWidget(history)
        tabs.addTab(notes_page, "跟进记录")

        footer = QHBoxLayout()
        footer.addWidget(label("修改将在点击“保存订单”后生效。", "hint"), 1)
        footer.addWidget(button("取消", self.reject))
        footer.addWidget(button("保存订单", self.save, "primary"))
        root.addSpacing(12)
        root.addLayout(footer)
        self.refresh()

    def refresh(self):
        self.items.setRowCount(0)
        for row, item in enumerate(self.order["items"]):
            put(self.items, row, [item["model"], item["quantity"],
                                  "已确认" if item["bom"] else "待确认",
                                  "已确认" if item["analyzed"] else "待确认",
                                  item["analysis_at"],
                                  "已确认" if item["packaging"] else "待确认",
                                  "完成" if item["completed"] else "进行中"])
            align_numbers(self.items, row, (1,))
        self.materials.setRowCount(0)
        for row, material in enumerate(self.order["materials"]):
            model = next(i["model"] for i in self.order["items"] if i["id"] == material["item_id"])
            put(self.materials, row, [model, material["name"], material["usage"], fmt(demand(self.order, material)),
                                      material.get("arrived", "0"), material.get("due_date", ""),
                                      material.get("remind_date") or material.get("due_date", "")])
            align_numbers(self.materials, row, (2, 3, 4))

    def bulk(self, key):
        if not self.order["items"]:
            QMessageBox.information(self, "提示", "请先添加型号")
            return
        done = all_checked(self.order, key)
        if done:
            if QMessageBox.question(self, "撤销整单确认", "此项已全部确认。是否撤销当前全部型号的此项确认？") != QMessageBox.StandardButton.Yes:
                return
        confirm_all(self.order, key, not done)
        self.refresh()

    def add_item(self):
        self.change_item(None)

    def edit_item(self):
        row = self.items.currentRow()
        if row >= 0:
            self.change_item(row)

    def change_item(self, row):
        dialog = ItemDialog(self.order["items"][row] if row is not None else new_item(), self)
        if dialog.exec():
            value = dialog.value()
            trial = copy.deepcopy(self.order)
            trial["number"] = trial["number"] or "校验"
            if row is None:
                trial["items"].append(value)
            else:
                trial["items"][row] = value
            try:
                validate_order(trial)
            except Exception as exc:
                QMessageBox.warning(self, "无法保存型号", str(exc))
                return
            self.order["items"] = trial["items"]
            self.refresh()

    def remove_item(self):
        row = self.items.currentRow()
        if row < 0:
            return
        item = self.order["items"][row]
        if any(material["item_id"] == item["id"] for material in self.order["materials"]):
            QMessageBox.warning(self, "无法移除", "此型号有关联包材，请先处理包材记录。")
            return
        if QMessageBox.question(self, "移除型号", f"移除 {item['model']}？保存订单后生效。") == QMessageBox.StandardButton.Yes:
            self.order["items"].pop(row)
            self.refresh()

    def add_material(self):
        self.change_material(None)

    def edit_material(self):
        row = self.materials.currentRow()
        if row >= 0:
            self.change_material(row)

    def change_material(self, row):
        if not self.order["items"]:
            QMessageBox.information(self, "提示", "请先在“型号与确认项”中添加型号")
            return
        trial = copy.deepcopy(self.order)
        trial["number"] = trial["number"] or "校验"
        dialog = MaterialDialog(trial, self.order["materials"][row] if row is not None else None, self)
        if dialog.exec():
            if row is None:
                self.order["materials"].append(dialog.material)
            else:
                self.order["materials"][row] = dialog.material
            self.refresh()

    def remove_material(self):
        row = self.materials.currentRow()
        if row >= 0 and QMessageBox.question(self, "移除包材", "移除此包材跟进记录？保存订单后生效。") == QMessageBox.StandardButton.Yes:
            self.order["materials"].pop(row)
            self.refresh()

    def save(self):
        self.order.update({key: widget.text().strip() for key, widget in self.fields.items()})
        self.order["received_at"] = self.received.dateTime().toString(Qt.DateFormat.ISODate)
        self.order["contract"] = self.contract.isChecked()
        self.order["notes"] = self.notes.toPlainText()
        try:
            self.store.save_order(self.order)
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", "订单号已存在，请使用其他订单号。" if "UNIQUE" in str(exc) else str(exc))
            return
        self.saved = True
        self.accept()


class ImportPreviewDialog(QDialog):
    """识别结果预览：订单摘要 + 明细 + 计划总表映射 + 待核对项。"""

    def __init__(self, orders, store, parent=None, source_name=""):
        super().__init__(parent)
        self.orders = orders
        self.store = store
        self.export_after = False
        self.setWindowTitle("导入预览")
        self.resize(1120, 760)
        self.setMinimumSize(940, 660)

        box = QVBoxLayout(self)
        box.setContentsMargins(26, 22, 26, 18)
        box.setSpacing(0)
        box.addWidget(label("导入预览", "dialogTitle", False))
        box.addSpacing(5)
        head = orders[0]
        total = sum(len(order["items"]) for order in orders)
        quantity = sum(Decimal(item["quantity"]) for order in orders for item in order["items"])
        pieces = [f"来源：{source_name or head.get('source_file', '手工表')}"]
        if head.get("source_titles"):
            pieces.append(" / ".join(head["source_titles"][:2]))
        box.addWidget(label("　·　".join(pieces), "hint"))
        box.addSpacing(12)

        summary = QFrame()
        summary.setObjectName("inner")
        grid = QHBoxLayout(summary)
        grid.setContentsMargins(16, 12, 16, 13)
        grid.setSpacing(26)
        facts = [("订单号", head.get("number", "")), ("客订编号", head.get("customer_no", "")),
                 ("业务员", head.get("owner", "")), ("接单日期", (head.get("received_at") or "")[:10]),
                 ("生产单交期", head.get("delivery_date", "")), ("运输方式", head.get("transport", "")),
                 ("订单属性", head.get("attribute", "")), ("型号数 / 合计数量", f"{total} / {fmt(quantity)}")]
        for title, value in facts:
            cell = QVBoxLayout()
            cell.setSpacing(3)
            cell.addWidget(label(title, "fieldLabel", False))
            cell.addWidget(label(value or "—", "meta", False))
            grid.addLayout(cell)
        grid.addStretch(1)
        box.addWidget(summary)
        box.addSpacing(12)

        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.tabBar().setExpanding(False)
        tabs.tabBar().setDrawBase(False)
        box.addWidget(tabs, 1)

        detail_page = QWidget()
        detail = QVBoxLayout(detail_page)
        detail.setContentsMargins(0, 12, 0, 0)
        items_table = table(["订单号", "型号", "物料代码", "类别", "数量", "单位", "包材", "BOM状态", "产品要求"],
                            widths=[130, 120, 156, 120, 70, 54, 60, 70, 0], stretch=8, height=38, right=(4,))
        for order in orders:
            for item in order["items"]:
                put(items_table, items_table.rowCount(),
                    [order["number"], item["model"], item.get("material_code", ""), item.get("category", ""),
                     item["quantity"], item.get("unit", ""), item.get("packaging_name", ""),
                     item.get("bom_status", ""), (item.get("requirement", "") or "").replace("\n", " ")])
                align_numbers(items_table, items_table.rowCount() - 1, (4,))
        detail.addWidget(panel(items_table, "识别到的产品明细", f"{total} 行")[0], 1)
        tabs.addTab(detail_page, "产品明细")

        plan_page = QWidget()
        plan_layout = QVBoxLayout(plan_page)
        plan_layout.setContentsMargins(0, 12, 0, 0)
        plan_table = table(["计划序列号", "订单号", "物料编码", "产品型号", "类别",
                            "电压", "频率", "功率", "数量", "接单日期", "生产单交期", "自制/外购"],
                           widths=[86, 108, 150, 96, 0, 56, 56, 56, 46, 100, 100, 62],
                           stretch=4, height=38, right=(5, 6, 7, 8))
        rows_total = 0
        for order in orders:
            rows, _ = plan_rows(order)
            for row in rows:
                put(plan_table, plan_table.rowCount(), [row[c] for c in
                    ["计划序列号", "订单号", "物料编码", "产品型号", "类别",
                     "电压(V)", "频率(Hz)", "功率(W)", "订单数量", "接单日期", "生产单交期", "自制/外购"]])
                align_numbers(plan_table, plan_table.rowCount() - 1, (5, 6, 7, 8))
                rows_total += 1
        plan_layout.addWidget(panel(plan_table, "计划总表映射（38 列中的关键列）", f"{rows_total} 行")[0], 1)

        serial_row = QHBoxLayout()
        serial_row.setSpacing(8)
        serial_row.addWidget(label("计划序列号", "fieldLabel", False))
        self.serial_edit = QLineEdit(self.store.get("plan_serial_next", ""))
        self.serial_edit.setPlaceholderText("留空则不填，可点右侧取号")
        self.serial_edit.setMinimumWidth(200)
        serial_row.addWidget(self.serial_edit)
        serial_row.addWidget(button("从计划总表取号", self.take_serial, icon_name="refresh"))
        serial_row.addStretch(1)
        serial_row.addWidget(label("导出总表行时写入 A 列", "hint", False))
        plan_layout.addLayout(serial_row)
        tabs.addTab(plan_page, "计划总表映射")

        warnings = []
        for order in orders:
            warnings.extend(order.get("warnings", []))
            warnings.extend(plan_rows(order)[1])
        if warnings:
            box.addSpacing(10)
            notice = QFrame()
            notice.setObjectName("inner")
            notice_layout = QVBoxLayout(notice)
            notice_layout.setContentsMargins(14, 10, 14, 11)
            notice_layout.setSpacing(4)
            notice_layout.addWidget(label(f"待核对 {len(warnings)} 项（不影响导入，导出前请确认）", "fieldLabel", False))
            for text in warnings[:6]:
                notice_layout.addWidget(label("· " + text, "hint"))
            if len(warnings) > 6:
                notice_layout.addWidget(label(f"· 其余 {len(warnings) - 6} 项见对应订单备注", "hint"))
            box.addWidget(notice)

        box.addSpacing(14)
        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addWidget(label(f"将新增 {len(orders)} 个订单、{total} 个型号；已有订单不会被覆盖。", "hint"), 1)
        footer.addWidget(button("取消", self.reject))
        footer.addWidget(button("导入并导出计划总表", self.accept_with_export))
        footer.addWidget(button("确认导入", self.accept, "primary"))
        box.addLayout(footer)

    def take_serial(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择计划总表", self.store.get("plan_path", ""),
                                              "Excel (*.xlsx)")
        if not path:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            serials, _ = read_plan_serials(path)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "读取失败", str(exc))
            return
        QApplication.restoreOverrideCursor()
        self.store.set("plan_path", path)
        self.serial_edit.setText(next_serial(serials + [self.serial_edit.text()]))

    def accept_with_export(self):
        self.export_after = True
        self.accept()

    def serials(self):
        value = self.serial_edit.text().strip()
        if not value:
            return {}
        result = {}
        for offset, order in enumerate(self.orders):
            if offset == 0:
                result[order["number"]] = value
            else:
                matched = re.fullmatch(r"([A-Za-z]*)(\d+)(\d{5})", value)
                result[order["number"]] = (f"{matched.group(1)}{matched.group(2)}"
                                           f"{int(matched.group(3)) + offset:05d}") if matched else value
        return result


class StatusStrip(QFrame):
    """窗口底部状态条：只覆盖内容区，不压到侧边栏。"""

    def __init__(self, text):
        super().__init__()
        self.setObjectName("statusStrip")
        self.setFixedHeight(32)
        self.default = text
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 0, 22, 0)
        layout.setSpacing(10)
        self.label = label(text, "statusText", False)
        layout.addWidget(self.label)
        layout.addStretch(1)
        layout.addWidget(label(f"v{VERSION}", "statusText", False))

    def showMessage(self, text, timeout=0):
        self.label.setText(text)
        if timeout:
            QTimer.singleShot(timeout, self, lambda: self.label.setText(self.default))


class Worker(QThread):
    success = Signal(object)
    failure = Signal(str)
    message = Signal(str)

    def __init__(self, fn, parent):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.success.emit(self.fn(self.message.emit))
        except Exception as exc:
            self.failure.emit(str(exc))


# ------------------------------------------------------------------ 主窗口
class MainWindow(QMainWindow):
    def __init__(self, store=None):
        super().__init__()
        self.store = store or Store()
        self.setWindowTitle(f"{APP_NAME} · v{VERSION}")
        self.setWindowIcon(app_icon())
        self.resize(1360, 880)
        self.setMinimumSize(1100, 720)
        self.workers = []
        self.quitting = False
        self.daily_dirty = False
        self.collapsed_groups = set()
        self.todo_groups = {}
        self.setAcceptDrops(True)

        central = QWidget()
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(238)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(0)

        brand = QWidget()
        brand_layout = QHBoxLayout(brand)
        brand_layout.setContentsMargins(22, 24, 18, 22)
        brand_layout.setSpacing(11)
        mark = QLabel()
        mark.setPixmap(brand_mark(36))
        brand_layout.addWidget(mark)
        titles = QVBoxLayout()
        titles.setSpacing(3)
        titles.addWidget(label(APP_NAME, "brandName", False))
        titles.addWidget(label(f"v{VERSION} · 本机数据", "brandMeta", False))
        brand_layout.addLayout(titles, 1)
        side.addWidget(brand)

        caption = QWidget()
        caption_layout = QHBoxLayout(caption)
        caption_layout.setContentsMargins(24, 2, 22, 8)
        caption_layout.addWidget(label("工作台", "navCaption", False))
        side.addWidget(caption)

        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(238)
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for title, _ in NAV:
            item = QListWidgetItem(title)
            item.setSizeHint(QSize(0, 42))
            self.nav.addItem(item)
        self.nav.setFixedHeight(sum(self.nav.sizeHintForRow(row) for row in range(self.nav.count())) + 4)
        side.addWidget(self.nav)

        summary_holder = QWidget()
        summary_layout = QVBoxLayout(summary_holder)
        summary_layout.setContentsMargins(16, 6, 16, 0)
        summary = QFrame()
        summary.setObjectName("sideCard")
        summary_box = QVBoxLayout(summary)
        summary_box.setContentsMargins(14, 12, 14, 13)
        summary_box.setSpacing(4)
        today = datetime.now()
        summary_box.addWidget(label(f"{today.month} 月 {today.day} 日 · 周{'一二三四五六日'[today.weekday()]}",
                                    "sideCardTitle", False))
        self.side_meta = label("进行中 0 单 · 待办 0 项", "sideCardMeta", False)
        summary_box.addWidget(self.side_meta)
        summary_layout.addWidget(summary)
        side.addWidget(summary_holder)
        side.addStretch(1)

        line = QFrame()
        line.setObjectName("sideLine")
        line.setFixedHeight(1)
        side.addWidget(line)
        foot = QWidget()
        foot_layout = QVBoxLayout(foot)
        foot_layout.setContentsMargins(22, 16, 22, 20)
        foot_layout.setSpacing(5)
        foot_layout.addWidget(label("数据保存在本机", "sideFootTitle", False))
        foot_layout.addWidget(label("不联网、不上传\n包材交期提醒 每天 09:00", "sideFoot"))
        side.addWidget(foot)
        outer.addWidget(sidebar)

        self.pages = QStackedWidget()
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self.pages, 1)
        self.status = StatusStrip("数据保存在本机  ·  自然日规则  ·  包材交期提醒 09:00")
        content_layout.addWidget(self.status)
        outer.addWidget(content, 1)

        self.dashboard()
        self.orders_page()
        self.materials_page()
        self.daily_page()
        self.settings_page()

        self.nav.currentRowChanged.connect(self.switch_page)
        self.nav.setCurrentRow(0)

        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        menu.addAction("打开工作台", self.show_normal)
        menu.addSeparator()
        menu.addAction("退出程序", self.exit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.show_normal()
                                    if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.tray.messageClicked.connect(self.show_normal)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(30000)
        self.build_drop_overlay()
        self.refresh()
        self.load_daily()
        QTimer.singleShot(1800, self.tick)

    # ---------- 拖拽导入 ----------
    def build_drop_overlay(self):
        self.drop_overlay = QFrame(self)
        self.drop_overlay.setObjectName("dropOverlay")
        self.drop_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout = QVBoxLayout(self.drop_overlay)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)
        mark = QLabel()
        mark.setPixmap(pixmap("import", ACCENT, 46, 1.6))
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(mark)
        title = label("松开即可识别导入", "dropTitle", False)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        hint = label("生产作业计划单或导入模板 · XLSX / CSV · 可同时拖多个 · 导入前会先给你确认",
                     "dropHint", False)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        self.drop_overlay.hide()

    @staticmethod
    def drop_paths(mime):
        if not mime.hasUrls():
            return []
        return [url.toLocalFile() for url in mime.urls()
                if url.toLocalFile() and Path(url.toLocalFile()).suffix.lower() in (".xlsx", ".xlsm", ".csv")]

    def dragEnterEvent(self, event):
        if self.drop_paths(event.mimeData()):
            event.acceptProposedAction()
            self.show_drop_overlay(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self.drop_paths(event.mimeData()):
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.show_drop_overlay(False)

    def dropEvent(self, event):
        paths = self.drop_paths(event.mimeData())
        self.show_drop_overlay(False)
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        self.import_files(paths)

    def show_drop_overlay(self, visible):
        if visible:
            self.drop_overlay.setGeometry(self.rect())
            self.drop_overlay.show()
            self.drop_overlay.raise_()
        else:
            self.drop_overlay.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "drop_overlay", None) is not None:
            self.drop_overlay.setGeometry(self.rect())

    # ---------- 结构 ----------
    def switch_page(self, index):
        self.pages.setCurrentIndex(index)
        for row, (_, name) in enumerate(NAV):
            self.nav.item(row).setIcon(icon(name, "#ffffff" if row == index else "#9db2d2", 18,
                                            1.9 if row == index else 1.8))

    def page(self, title, subtitle, actions=()):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(30, 26, 30, 18)
        root.setSpacing(0)
        head = QHBoxLayout()
        head.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(6)
        titles.addWidget(label(title, "title", False))
        titles.addWidget(label(subtitle, "subtitle"))
        head.addLayout(titles, 1)
        if actions:
            action_row = QHBoxLayout()
            action_row.setSpacing(8)
            for widget in actions:
                action_row.addWidget(widget)
            head.addLayout(action_row)
        root.addLayout(head)
        root.addSpacing(18)
        body = QVBoxLayout()
        body.setSpacing(14)
        root.addLayout(body, 1)
        self.pages.addWidget(page)
        return body

    def table_card(self, title, table_widget, meta=""):
        return panel(table_widget, title, meta)

    # ---------- 页面 ----------
    def dashboard(self):
        body = self.page("今日待办", "按优先级排列，双击任意一行进入订单详情。",
                         [button("导入订单", self.import_orders, icon_name="import"),
                          button("登记新订单", lambda: self.edit_order(), "primary", "plus")])

        stats = QHBoxLayout()
        stats.setSpacing(14)
        self.stats = []
        cards = [("进行中的订单", "inbox", ACCENT, "#eaf1fe"),
                 ("高优先级订单", "alert", WARN, "#fdf3e2"),
                 ("待确认包材信息", "package", "#7a5cd8", "#f1ecfe"),
                 ("未解决每日跟进", "clock", SUCCESS, "#e7f6ef")]
        for title, name, tint, background in cards:
            frame = QFrame()
            frame.setObjectName("card")
            layout = QHBoxLayout(frame)
            layout.setContentsMargins(17, 16, 17, 16)
            layout.setSpacing(13)
            layout.addWidget(chip(name, tint, background, 40))
            text = QVBoxLayout()
            text.setSpacing(3)
            text.addWidget(label(title, "muted", False))
            value = label("0", "stat", False)
            text.addWidget(value)
            self.stats.append(value)
            layout.addLayout(text, 1)
            shadow(frame)
            stats.addWidget(frame, 1)
        body.addLayout(stats)

        self.todo = table(["优先级", "订单号", "客户", "型号 / 范围", "待办事项", "经办人"],
                          widths=[76, 142, 112, 132, 0, 82], stretch=4)
        self.todo.setItemDelegateForColumn(0, BadgeDelegate(self.todo))
        self.todo.cellDoubleClicked.connect(lambda row, col: self.open_identity(self.todo, row))
        self.todo.cellClicked.connect(self.toggle_todo_group)
        self.todo.setToolTip("同一订单合并成一组，单击组头展开或折叠，双击进入订单详情。")
        frame, self.todo_meta = self.table_card("待办清单", self.todo, "0 项")
        self.empty = label("暂无待办。登记或导入订单后，未完成事项会自动列在这里。", "muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        frame.layout().addWidget(self.empty, 1)
        body.addWidget(frame, 1)

    def orders_page(self):
        body = self.page("订单总表", "以整单跟进为主，每个型号保留独立确认；完成的订单仍可查询和重新打开。",
                         [button("导入模板", self.template, icon_name="template"),
                          button("导入订单表", self.import_orders, icon_name="import"),
                          button("导出计划总表", self.export_plan_menu, icon_name="export"),
                          button("新订单", lambda: self.edit_order(), "primary", "plus")])

        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索订单号、客户、型号、合同 / 销售单号、经办人")
        self.search.addAction(icon("search", FAINT, 15), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.filter = QComboBox()
        self.filter.addItems(["全部订单", "进行中", "高优先级", "已完成"])
        self.filter.setMinimumWidth(118)
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(self.filter)
        body.addLayout(toolbar)

        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.tabBar().setExpanding(False)
        tabs.tabBar().setDrawBase(False)
        self.order_tabs = tabs
        body.addWidget(tabs, 1)

        self.orders_table = table(ORDERS_HEADERS, widths=ORDERS_WIDTHS, height=38, right=ORDERS_RIGHT_COLUMNS)
        self.orders_table.setItemDelegateForColumn(0, BadgeDelegate(self.orders_table))
        fit_headers(self.orders_table, ORDERS_HEADERS)
        self.orders_table.cellDoubleClicked.connect(lambda row, col: self.open_identity(self.orders_table, row))
        self.orders_table.setToolTip("按型号一行，列顺序与《2026年新能源新计划》「最新」表一致；双击进入订单详情。")
        frame, self.order_count = panel(self.orders_table, "整机订单 · 列对齐「最新」表", "0 行")
        tabs.addTab(frame, "整机订单")

        self.parts_table = table(PARTS_COLUMNS, widths=PARTS_WIDTHS, height=38, right=PARTS_RIGHT)
        fit_headers(self.parts_table, PARTS_COLUMNS)
        self.parts_table.cellDoubleClicked.connect(lambda row, col: self.open_identity(self.parts_table, row))
        self.parts_table.setToolTip("列对齐「整体配件汇总」：按型号汇总，月份、客户、未发货、包材、物料代码。")
        parts_frame, self.parts_meta = panel(self.parts_table, "整体配件汇总", "0 行")
        tabs.addTab(parts_frame, "整体配件汇总")

        self.home_table = table(HOME_COLUMNS, widths=HOME_WIDTHS, height=38, right=HOME_RIGHT)
        fit_headers(self.home_table, HOME_COLUMNS)
        self.home_table.cellDoubleClicked.connect(lambda row, col: self.open_identity(self.home_table, row))
        self.home_table.setToolTip("列对齐「家用机订单」：计划序号、月份、规格、产品交期、剩余数量。")
        home_frame, self.home_meta = panel(self.home_table, "家用机订单", "0 行")
        tabs.addTab(home_frame, "家用机订单")

        self.pack_table = table(PACKAGING_COLUMNS, widths=PACKAGING_WIDTHS, height=38)
        fit_headers(self.pack_table, PACKAGING_COLUMNS)
        self.pack_table.cellDoubleClicked.connect(lambda row, col: self.open_identity(self.pack_table, row))
        self.pack_table.setToolTip("列对齐「包材资料未确定」：只列还没确认包材信息的型号，预留时间按交期前 15 天推算。")
        pack_frame, self.pack_meta = panel(self.pack_table, "包材资料未确定", "0 行")
        tabs.addTab(pack_frame, "包材资料未确定")

        self.search.textChanged.connect(self.refresh)
        self.filter.currentIndexChanged.connect(self.refresh)

        footer = QHBoxLayout()
        footer.addWidget(button("打开所选订单", self.open_selected_order))
        footer.addStretch(1)
        footer.addWidget(label("双击任意一行进入订单详情；列顺序与计划总表各 sheet 对应", "meta", False))
        body.addLayout(footer)

    def open_selected_order(self):
        table_widget = self.order_tabs.currentWidget().findChild(QTableWidget)
        if table_widget is not None:
            self.open_identity(table_widget, table_widget.currentRow())

    def materials_page(self):
        body = self.page("包材跟进", "请购数量 = 产品数量 × 单件用量。双击记录可进入订单，更新交期与到料。")
        row = QHBoxLayout()
        row.setSpacing(10)
        self.material_filter = QComboBox()
        self.material_filter.addItems(["全部包材", "未到齐", "已到齐"])
        self.material_filter.setMinimumWidth(118)
        self.material_filter.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.material_filter)
        row.addStretch(1)
        row.addWidget(label("到齐后自动停止提醒", "meta", False))
        body.addLayout(row)

        self.material_table = table(["订单号", "型号", "包材", "请购数量", "单位", "已到", "未到", "预计交期", "提醒日 09:00", "请购单号"],
                                    widths=[136, 132, 0, 92, 56, 66, 66, 104, 112, 128], stretch=2, right=(3, 5, 6))
        self.material_table.cellDoubleClicked.connect(lambda row, col: self.open_identity(self.material_table, row))
        frame, self.material_meta = self.table_card("包材明细", self.material_table, "")
        body.addWidget(frame, 1)

    def daily_page(self):
        body = self.page("每日跟进", "数据在其他系统刷新；这里只记录检查结果、是否需要跟进及处理进展。未解决事项会并入今日待办。",
                         [button("保存当日记录", self.save_daily, "primary", "check")])
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(label("记录日期", "fieldLabel", False))
        self.daily_date = date_field()
        self.daily_date.setFixedWidth(160)
        self.daily_date.dateChanged.connect(self.date_changed)
        row.addWidget(self.daily_date)
        row.addStretch(1)
        row.addWidget(label("状态与备注修改后自动保存", "meta", False))
        body.addLayout(row)

        palette = [("分仓数据", "package", ACCENT, "#eaf1fe"), ("成品入库数据", "inbox", "#7a5cd8", "#f1ecfe"),
                   ("销售出库数据", "activity", SUCCESS, "#e7f6ef")]
        self.daily_widgets = {}
        for key, name, tint, background in palette:
            frame = QFrame()
            frame.setObjectName("card")
            layout = QHBoxLayout(frame)
            layout.setContentsMargins(16, 13, 16, 13)
            layout.setSpacing(12)
            layout.addWidget(chip(name, tint, background, 32))
            layout.addWidget(label(key, "section", False), 0)
            state = QComboBox()
            state.addItems(["待检查", "无需跟进", "需要跟进", "已处理"])
            state.setFixedWidth(126)
            layout.addWidget(state)
            notes = QLineEdit()
            notes.setPlaceholderText("关联订单、经办人、异常情况与处理进展……")
            layout.addWidget(notes, 1)
            body.addWidget(frame)
            self.daily_widgets[key] = (state, notes)
            state.currentIndexChanged.connect(self.autosave_daily)
            notes.editingFinished.connect(self.autosave_daily)

        self.daily_history = table(["记录日期", "分仓数据", "成品入库数据", "销售出库数据"],
                                   widths=[104, 0, 0, 0])
        for column in (1, 2, 3):
            self.daily_history.setItemDelegateForColumn(column, StatusDelegate(self.daily_history))
            self.daily_history.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        self.daily_history.cellDoubleClicked.connect(self.open_daily_history)
        history_frame, _ = panel(self.daily_history, "近 7 天记录", "双击可切换到该日期")
        body.addWidget(history_frame, 1)
        self.current_daily_day = date.today().isoformat()
        self.loading_daily = False

    def settings_page(self):
        body = self.page("设置与更新", f"{APP_NAME}  v{VERSION}  ·  Windows 桌面版")
        columns = QHBoxLayout()
        columns.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(14)
        right = QVBoxLayout()
        right.setSpacing(14)
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)

        rules = QFrame()
        rules.setObjectName("card")
        rules_layout = QVBoxLayout(rules)
        rules_layout.setContentsMargins(20, 17, 20, 18)
        rules_layout.setSpacing(10)
        rules_layout.addWidget(label("提醒规则", "section", False))
        rules_layout.addSpacing(2)
        for text in ["合同：接单满 24 小时仍未确认，提升为高优先级。",
                     "包材信息：分析日期满 10 个自然日仍未确认，提升为高优先级。",
                     "包材交期：提醒日 09:00 起提示；未填写提醒日时使用预计交期。",
                     "整单跟进完成后停止该单提醒；单个型号完成只停该型号。"]:
            rules_layout.addLayout(rule_row(text))
        left.addWidget(rules)

        runtime = QFrame()
        runtime.setObjectName("card")
        runtime_layout = QVBoxLayout(runtime)
        runtime_layout.setContentsMargins(20, 17, 20, 18)
        runtime_layout.setSpacing(10)
        runtime_layout.addWidget(label("运行方式", "section", False))
        self.tray_check = QCheckBox("关闭窗口后保留在系统托盘，继续提醒")
        self.tray_check.setChecked(self.store.get("tray", "1") == "1")
        self.tray_check.toggled.connect(lambda value: self.store.set("tray", "1" if value else "0"))
        runtime_layout.addWidget(self.tray_check)
        self.startup = QCheckBox("登录 Windows 后自动启动（最小化到托盘）")
        self.startup.setChecked(self.startup_enabled())
        self.startup.toggled.connect(self.change_startup)
        runtime_layout.addWidget(self.startup)
        runtime_layout.addWidget(label("准点提醒需要程序正在运行且电脑已开机；若 09:00 未运行，打开后会补查。", "hint"))
        left.addWidget(runtime)
        left.addStretch(1)

        backup = QFrame()
        backup.setObjectName("card")
        backup_layout = QVBoxLayout(backup)
        backup_layout.setContentsMargins(20, 17, 20, 18)
        backup_layout.setSpacing(12)
        backup_layout.addWidget(label("数据与备份", "section", False))
        backup_layout.addWidget(label("全部数据保存在本机数据库，不上传任何服务器；恢复前会自动备份当前数据。", "hint"))
        db_line = QFrame()
        db_line.setObjectName("inner")
        db_layout = QVBoxLayout(db_line)
        db_layout.setContentsMargins(13, 10, 13, 11)
        db_layout.setSpacing(3)
        db_layout.addWidget(label("数据库位置", "fieldLabel", False))
        path_text = QFontMetrics(self.font()).elidedText(str(self.store.path), Qt.TextElideMode.ElideMiddle, 340)
        path_label = label(path_text, "meta", False)
        path_label.setToolTip(str(self.store.path))
        db_layout.addWidget(path_label)
        backup_layout.addWidget(db_line)
        backup_layout.addLayout(ghost_row(button("导出数据备份", self.export_backup, icon_name="database"),
                                          button("从备份恢复", self.restore_backup, icon_name="refresh"),
                                          button("打开数据目录",
                                                 lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir()))),
                                                 icon_name="folder")))
        backup_layout.addStretch(1)
        right.addWidget(backup)

        version = QFrame()
        version.setObjectName("card")
        version_layout = QVBoxLayout(version)
        version_layout.setContentsMargins(20, 17, 20, 18)
        version_layout.setSpacing(12)
        version_layout.addWidget(label("版本更新", "section", False))
        version_layout.addWidget(label(f"当前版本 v{VERSION}。更新会校验下载文件、自动备份数据库，再替换程序并重启。", "hint"))
        self.update_button = button("检查新版本", self.check_update, "primary", "refresh")
        version_layout.addLayout(ghost_row(self.update_button,
                                           button("打开 GitHub 项目",
                                                  lambda: QDesktopServices.openUrl(QUrl(f"https://github.com/{REPOSITORY}")),
                                                  icon_name="external")))
        self.update_status = label("尚未检查更新。", "hint")
        version_layout.addWidget(self.update_status)
        version_layout.addStretch(1)
        right.addWidget(version)
        right.addStretch(1)

        body.addLayout(columns, 1)

    # ---------- 数据刷新 ----------
    def refresh(self, *args):
        if not hasattr(self, "material_table"):
            return
        orders = self.store.orders()
        orders.sort(key=lambda order: (all_checked(order, "completed"),
                                       -max((reminder["level"] for reminder in reminders(order)), default=0)))
        self.by_id = {order["id"]: order for order in orders}
        self.todo.setRowCount(0)
        self.orders_table.setRowCount(0)
        self.parts_table.setRowCount(0)
        self.home_table.setRowCount(0)
        self.pack_table.setRowCount(0)
        self.material_table.setRowCount(0)
        tasks = []
        elevated = 0
        waiting = 0
        active = 0
        missing_total = 0
        for order in orders:
            due = reminders(order)
            completed = all_checked(order, "completed")
            rank = max([reminder["level"] for reminder in due], default=0)
            active += not completed
            elevated += bool(rank)
            waiting += sum(item["analyzed"] and not item["packaging"] and not item["completed"] for item in order["items"])
            priority = "已完成" if completed else ("紧急" if rank == 3 else "高" if rank == 2 else "正常")
            keyword = self.search.text().strip().lower()
            searchable = " ".join(str(order.get(key, "")) for key in
                                  ["number", "customer", "customer_no", "owner", "transport", "attribute",
                                   "contract_no", "contract_owner", "sales_no", "sales_owner"])
            searchable += " " + " ".join(item["model"] for item in order["items"])
            searchable += " " + " ".join(item.get("material_code", "") for item in order["items"])
            customer_label = order.get("customer") or order.get("customer_no", "")
            filter_index = self.filter.currentIndex()
            visible = (not keyword or keyword in searchable.lower()) and (
                filter_index == 0 or filter_index == 1 and not completed or filter_index == 2 and rank > 0
                or filter_index == 3 and completed)
            if visible:
                follow = " · ".join([f"合同{'已确认' if order['contract'] else '待确认'}",
                                     f"BOM {progress(order, 'bom')}", f"分析 {progress(order, 'analyzed')}",
                                     f"包材 {progress(order, 'packaging')}", f"完成 {progress(order, 'completed')}"])
                for values in plan_rows(order, order.get("plan_serial", ""))[0]:
                    row = self.orders_table.rowCount()
                    put(self.orders_table, row,
                        [priority] + [values[column] for column in PLAN_COLUMNS] + [follow], order["id"])
                    align_numbers(self.orders_table, row, ORDERS_RIGHT_COLUMNS)
                for values in parts_rows(order):
                    row = self.parts_table.rowCount()
                    put(self.parts_table, row, [values[column] for column in PARTS_COLUMNS], order["id"])
                    align_numbers(self.parts_table, row, PARTS_RIGHT)
                for values in home_rows(order):
                    row = self.home_table.rowCount()
                    put(self.home_table, row, [values[column] for column in HOME_COLUMNS], order["id"])
                    align_numbers(self.home_table, row, HOME_RIGHT)
                for values in packaging_rows(order):
                    row = self.pack_table.rowCount()
                    put(self.pack_table, row, [values[column] for column in PACKAGING_COLUMNS], order["id"])
            for reminder in due:
                owner = order.get("contract_owner") or order["owner"] if reminder["kind"] == "contract" else order["owner"]
                tasks.append((reminder["level"], order["number"], customer_label, reminder["model"],
                              reminder["reason"], owner, order["id"]))
            if not completed:
                if not order["contract"] and not any(reminder["kind"] == "contract" for reminder in due):
                    tasks.append((0, order["number"], customer_label, "整单", "待确认合同录入",
                                  order.get("contract_owner") or order["owner"], order["id"]))
                for key, title in [("bom", "待确认工程 BOM"), ("analyzed", "待确认分析")]:
                    missing = [item["model"] for item in order["items"] if not item[key] and not item["completed"]]
                    if missing:
                        tasks.append((0, order["number"], customer_label, "、".join(missing), title,
                                      order["owner"], order["id"]))
            for material in order["materials"]:
                quantity = demand(order, material)
                arrived = updater_decimal(material.get("arrived", 0))
                missing_quantity = max(0, quantity - arrived)
                missing_total += missing_quantity > 0
                mode = self.material_filter.currentIndex()
                if mode == 1 and missing_quantity <= 0 or mode == 2 and missing_quantity > 0:
                    continue
                model = next(item["model"] for item in order["items"] if item["id"] == material["item_id"])
                row = self.material_table.rowCount()
                put(self.material_table, row,
                    [order["number"], model, material["name"], fmt(quantity), material.get("unit", "个"),
                     fmt(arrived), fmt(missing_quantity), material.get("due_date", ""),
                     material.get("remind_date") or material.get("due_date", ""), material.get("request_no", "")],
                    order["id"])
                align_numbers(self.material_table, row, (3, 5, 6))
                due_date = material.get("due_date")
                if missing_quantity > 0 and due_date and date.fromisoformat(due_date) < date.today():
                    self.material_table.item(row, 6).setForeground(QColor(DANGER))
        daily_pending = 0
        for day, records in self.store.daily_all():
            for key, record in records.items():
                if record.get("state") == "需要跟进":
                    daily_pending += 1
                    tasks.append((1, "每日记录", day, key, record.get("notes") or "需要跟进", "", f"daily:{day}"))
        self.render_todo(tasks)
        for widget, value in zip(self.stats, [active, elevated, waiting, daily_pending]):
            widget.setText(str(value))
        self.empty.setVisible(not tasks)
        self.todo.setVisible(bool(tasks))
        self.todo_meta.setText(f"{len(tasks)} 项待处理")
        self.side_meta.setText(f"进行中 {active} 单 · 待办 {len(tasks)} 项")
        shown = self.orders_table.rowCount()
        self.order_count.setText(f"显示 {shown} 行 / 共 {len(orders)} 单")
        self.parts_meta.setText(f"{self.parts_table.rowCount()} 行")
        self.home_meta.setText(f"{self.home_table.rowCount()} 行")
        self.pack_meta.setText(f"{self.pack_table.rowCount()} 行")
        self.material_meta.setText(f"未到齐 {missing_total} 项")

    def open_identity(self, widget, row):
        if row < 0:
            return
        identity = widget.item(row, 0).data(Qt.ItemDataRole.UserRole)
        if identity.startswith("daily:"):
            self.daily_date.setDate(QDate.fromString(identity[6:], "yyyy-MM-dd"))
            self.nav.setCurrentRow(3)
        else:
            self.edit_order(self.by_id.get(identity))

    def render_todo(self, tasks):
        """待办清单：同一订单合并成一组，组头可展开 / 折叠，单击切换。"""
        self.todo.setRowCount(0)
        self.todo_groups = {}
        groups, keys = {}, []
        for task in sorted(tasks, key=lambda item: -item[0]):
            key = task[6]
            if key not in groups:
                groups[key] = []
                keys.append(key)
            groups[key].append(task)
        for key in keys:
            rows = groups[key]
            if len(rows) == 1:
                task = rows[0]
                row = self.todo.rowCount()
                put(self.todo, row, [self.todo_label(task[0]), task[1], task[2], task[3], task[4], task[5]], key)
                self.mark_todo(row, "single")
                continue
            top = max(task[0] for task in rows)
            collapsed = key in self.collapsed_groups
            reasons = [task[4] for task in rows]
            summary = " · ".join(reasons[:2]) + (f" 等 {len(reasons)} 项" if len(reasons) > 2 else "")
            if len(summary) > 60:
                summary = summary[:59] + "…"
            header = self.todo.rowCount()
            put(self.todo, header, [self.todo_label(top), f"{'＋' if collapsed else '－'} {rows[0][1]}",
                                    rows[0][2], f"{len(rows)} 项待办", summary, rows[0][5]], key)
            for column in range(self.todo.columnCount()):
                item = self.todo.item(header, column)
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                item.setBackground(QColor("#f1f6ff"))
            self.mark_todo(header, "group")
            children = []
            for task in rows:
                row = self.todo.rowCount()
                put(self.todo, row, ["", "", "", "　└ " + task[3], task[4], ""], key)
                self.mark_todo(row, "child")
                children.append(row)
            for row in children:
                self.todo.setRowHidden(row, collapsed)
            self.todo_groups[key] = (header, children)

    def mark_todo(self, row, marker):
        for column in range(self.todo.columnCount()):
            item = self.todo.item(row, column)
            if item is not None:
                item.setData(Qt.ItemDataRole.UserRole + 1, marker)

    @staticmethod
    def todo_label(rank):
        return "紧急" if rank == 3 else "高" if rank == 2 else "待跟进" if rank == 1 else "正常"

    def toggle_todo_group(self, row, column):
        if row < 0:
            return
        item = self.todo.item(row, 0)
        if item is None or item.data(Qt.ItemDataRole.UserRole + 1) != "group":
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        header, children = self.todo_groups.get(key, (row, []))
        collapsed = key not in self.collapsed_groups
        if collapsed:
            self.collapsed_groups.add(key)
        else:
            self.collapsed_groups.discard(key)
        for child in children:
            self.todo.setRowHidden(child, collapsed)
        label_item = self.todo.item(header, 1)
        if label_item is not None:
            text = label_item.text()
            label_item.setText(text.replace("－", "＋") if collapsed else text.replace("＋", "－"))

    def edit_order(self, order=None):
        dialog = OrderDialog(self.store, order, self)
        if dialog.exec():
            self.refresh()

    def template(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存导入模板", "订单导入模板.xlsx", "Excel (*.xlsx);;CSV (*.csv)")
        if path:
            try:
                write_template(path)
                QMessageBox.information(self, "模板已保存", "订单号、型号、产品数量必填。同一订单可分多行填写不同型号。示例行请替换后再导入。")
            except Exception as exc:
                QMessageBox.warning(self, "保存失败", str(exc))

    def import_orders(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "导入订单 / 生产单", "", "订单文件 (*.xlsx *.xlsm *.csv);;Excel (*.xlsx *.xlsm);;CSV (*.csv)")
        if paths:
            self.import_files(paths)

    def import_files(self, paths):
        """统一入口：拖拽和文件对话框都走这里，先解析再确认。"""
        existing = [order["number"] for order in self.store.orders()]
        orders, errors = [], []
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for path in paths:
                try:
                    orders.extend(read_any(path, existing + [order["number"] for order in orders]))
                except Exception as exc:
                    errors.append(f"{Path(path).name}：{exc}")
        finally:
            QApplication.restoreOverrideCursor()
        if errors:
            QMessageBox.warning(self, "导入检查", "以下文件没有导入：\n" + "\n".join(errors[:10]))
            return
        if not orders:
            QMessageBox.warning(self, "导入检查", "没有解析到可导入的订单")
            return
        source = "、".join(Path(path).name for path in paths[:2])
        if len(paths) > 2:
            source += f" 等 {len(paths)} 个文件"
        self.confirm_import(orders, source)

    def confirm_import(self, orders, source):
        dialog = ImportPreviewDialog(orders, self.store, self, source)
        if not dialog.exec():
            return
        serials = dialog.serials()
        for order in orders:
            if serials.get(order["number"]):
                order["plan_serial"] = serials[order["number"]]
        try:
            self.store.save_orders(orders)
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "导入失败", str(exc))
            return
        self.status.showMessage(f"已新增 {len(orders)} 个订单", 5000)
        if dialog.export_after:
            self.write_plan(orders, serials)
        else:
            QMessageBox.information(self, "导入完成",
                                    f"已新增 {len(orders)} 个订单。\n如需填入计划总表，可在「订单总表」选中后点「导出总表行」。")

    def write_plan(self, orders, serials=None):
        default_name = f"计划总表导入_{orders[0]['number']}_{date.today():%Y%m%d}.xlsx"
        target = Path(self.store.get("plan_path", ""))
        start = str(target.parent / default_name) if target.parent.exists() else str(Path.home() / "Desktop" / default_name)
        path, _ = QFileDialog.getSaveFileName(self, "导出计划总表", start, "Excel (*.xlsx)")
        if not path:
            return
        try:
            counts = export_plan_book(path, orders, serials or {})
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        detail = "\n".join(f"　{name}：{count} 行" for name, count in counts.items())
        QMessageBox.information(
            self, "导出完成",
            f"已按计划总表的 sheet 结构导出：\n{detail}\n\n{path}\n\n"
            "每个 sheet 的表头与列顺序都和原总表一致，整表选中数据行粘贴到对应 sheet 末尾即可；原总表未被改动。")

    def export_plan_menu(self):
        menu = QMenu(self)
        menu.addAction("仅导出选中订单（4 个 sheet）", self.export_plan_selected)
        menu.addAction("导出当前筛选结果（4 个 sheet）", self.export_plan_visible)
        menu.exec(QCursor.pos())

    def export_plan_visible(self):
        seen, orders = set(), []
        for row in range(self.orders_table.rowCount()):
            item = self.orders_table.item(row, 0)
            identity = item.data(Qt.ItemDataRole.UserRole) if item else None
            if identity and identity not in seen:
                order = self.by_id.get(identity)
                if order:
                    seen.add(identity)
                    orders.append(order)
        if not orders:
            QMessageBox.information(self, "没有可导出的订单", "当前筛选结果为空。")
            return
        self.write_plan(orders, {order["number"]: order.get("plan_serial", "") for order in orders})

    def export_plan_selected(self):
        row = self.orders_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "请先选择订单", "在订单列表中点选一行，再导出该单的计划总表行。")
            return
        identity = self.orders_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        order = self.by_id.get(identity)
        if not order:
            return
        serial = order.get("plan_serial", "")
        if not serial:
            path = self.store.get("plan_path", "")
            if path and Path(path).exists():
                try:
                    serials, _ = read_plan_serials(path)
                    serial = next_serial(serials)
                except Exception:
                    serial = ""
        self.write_plan([order], {order["number"]: serial} if serial else {})

    def date_changed(self, *args):
        if not hasattr(self, "current_daily_day"):
            return
        self.save_daily(silent=True)
        self.load_daily()

    def load_daily(self):
        self.loading_daily = True
        self.current_daily_day = self.daily_date.date().toString("yyyy-MM-dd")
        records = self.store.daily(self.current_daily_day)
        for key, (state, notes) in self.daily_widgets.items():
            state.setCurrentText(records.get(key, {}).get("state", "待检查"))
            notes.setText(records.get(key, {}).get("notes", ""))
        self.loading_daily = False
        self.load_daily_history()

    def load_daily_history(self):
        self.daily_history.setRowCount(0)
        records = dict(self.store.daily_all())
        for offset in range(7):
            day = (date.today() - timedelta(days=offset)).isoformat()
            entry = records.get(day, {})
            values = [day] + [entry.get(key, {}).get("state") or "—"
                              for key in ("分仓数据", "成品入库数据", "销售出库数据")]
            put(self.daily_history, self.daily_history.rowCount(), values, f"daily:{day}")

    def open_daily_history(self, row, column=0):
        identity = self.daily_history.item(row, 0).data(Qt.ItemDataRole.UserRole)
        if identity and identity.startswith("daily:"):
            self.daily_date.setDate(QDate.fromString(identity[6:], "yyyy-MM-dd"))

    def autosave_daily(self, *args):
        if not getattr(self, "loading_daily", True):
            self.save_daily(silent=True)

    def save_daily(self, checked=False, silent=False):
        if getattr(self, "loading_daily", False):
            return
        payload = {key: dict(state=state.currentText(), notes=notes.text(),
                             updated_at=datetime.now().isoformat(timespec="seconds"))
                   for key, (state, notes) in self.daily_widgets.items()}
        try:
            self.store.save_daily(self.current_daily_day, payload)
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        if not silent:
            self.status.showMessage(f"已保存 {self.current_daily_day} 的跟进记录", 5000)

    def tick(self):
        self.refresh()
        now = datetime.now()
        due = [(order, reminders(order, now)) for order in self.store.orders()]
        due = [(order, reminder) for order, reminder in due if reminder]
        key = now.date().isoformat() + ":" + "|".join(sorted(order["id"] + str(len(reminder)) for order, reminder in due))
        if now.hour >= 9 and due and self.store.get("notified") != key:
            self.tray.showMessage(APP_NAME, f"{len(due)} 个订单有高优先级事项，请打开工作台查看。",
                                  QSystemTrayIcon.MessageIcon.Information, 10000)
            self.store.set("notified", key)

    def export_backup(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出数据备份", f"订单工作台备份-{date.today()}.json", "备份 (*.json)")
        if path:
            try:
                self.store.export_json(path)
                QMessageBox.information(self, "备份完成", "全部订单、包材、每日记录和保存历史已导出。")
            except Exception as exc:
                QMessageBox.warning(self, "备份失败", str(exc))

    def restore_backup(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择数据备份", "", "备份 (*.json)")
        if path and QMessageBox.question(self, "恢复备份", "恢复会替换当前数据。程序会先自动备份现有数据库，是否继续？") == QMessageBox.StandardButton.Yes:
            try:
                backup = self.store.restore_json(path)
                self.load_daily()
                self.refresh()
                QMessageBox.information(self, "恢复完成", f"恢复成功。替换前的数据备份在：\n{backup}")
            except Exception as exc:
                QMessageBox.warning(self, "恢复失败", str(exc))

    def startup_enabled(self):
        if sys.platform != "win32":
            return False
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                return bool(winreg.QueryValueEx(key, "OrderFollowupDesktop")[0])
        except OSError:
            return False

    def change_startup(self, enabled):
        try:
            if not getattr(sys, "frozen", False):
                raise ValueError("请在打包后的 Windows 程序中设置开机启动")
            import winreg
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                if enabled:
                    winreg.SetValueEx(key, "OrderFollowupDesktop", 0, winreg.REG_SZ, f'"{sys.executable}" --minimized')
                else:
                    try:
                        winreg.DeleteValue(key, "OrderFollowupDesktop")
                    except FileNotFoundError:
                        pass
        except Exception as exc:
            self.startup.blockSignals(True)
            self.startup.setChecked(self.startup_enabled())
            self.startup.blockSignals(False)
            QMessageBox.warning(self, "设置未完成", str(exc))

    def run_worker(self, fn, success):
        worker = Worker(fn, self)
        self.workers.append(worker)
        worker.message.connect(self.update_status.setText)
        worker.success.connect(success)
        worker.failure.connect(self.update_error)
        worker.finished.connect(lambda: self.workers.remove(worker))
        worker.start()

    def check_update(self):
        self.update_button.setEnabled(False)
        self.update_status.setText("正在查询 GitHub 最新版本……")
        self.run_worker(lambda _: updater.get_release(), self.release_ready)

    def update_error(self, message):
        self.update_button.setEnabled(True)
        self.update_status.setText("更新未完成：" + message)

    def release_ready(self, release):
        self.update_button.setEnabled(True)
        if updater.version_tuple(release["tag_name"]) <= updater.version_tuple(VERSION):
            self.update_status.setText(f"当前 v{VERSION} 已是最新版本。")
            return
        if not getattr(sys, "frozen", False):
            self.update_status.setText("开发模式：发现 " + release["tag_name"] + "，请在 Windows 程序中更新。")
            return
        if QMessageBox.question(self, "发现新版本", f"当前 v{VERSION} → {release['tag_name']}\n下载、备份数据并重启更新？") != QMessageBox.StandardButton.Yes:
            return
        self.update_button.setEnabled(False)
        self.update_status.setText("正在下载并校验更新包……")
        self.run_worker(lambda emit: updater.download_release(release, emit), self.download_ready)

    def download_ready(self, path):
        try:
            self.store.backup()
            updater.launch_replacement(path)
        except Exception as exc:
            self.update_error(str(exc))
            return
        self.quitting = True
        QTimer.singleShot(300, self.exit_app)

    def show_normal(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        self.save_daily(silent=True)
        if not self.quitting and self.tray_check.isChecked() and self.tray.isVisible():
            self.hide()
            event.ignore()
            return
        if self.workers:
            event.ignore()
            QMessageBox.information(self, "正在更新", "请等待版本查询或下载结束后退出。")
            return
        event.accept()
        self.tray.hide()

    def exit_app(self):
        if self.workers:
            QTimer.singleShot(500, self.exit_app)
            return
        self.quitting = True
        self.save_daily(silent=True)
        self.tray.hide()
        QApplication.instance().quit()


def updater_decimal(value):
    return Decimal(str(value))
