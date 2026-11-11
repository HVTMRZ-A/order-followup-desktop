"""界面主题：配色、矢量图标、绘制代理与全局样式表。

界面层的所有视觉常量集中在这里，改配色只需改本文件顶部的色板。
图标全部用内联 SVG 渲染，不依赖外部图片资源，打包后同样可用。
"""
import tempfile
from pathlib import Path

from PySide6.QtCore import QByteArray, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QIcon, QImage, QLinearGradient,
                           QPainter, QPen, QPixmap, QPolygonF)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem

# ---------------------------------------------------------------- 色板
INK = "#16202f"          # 主文字
INK_SOFT = "#3b4a60"     # 次级文字
MUTED = "#6b7891"        # 说明文字
FAINT = "#98a4b7"        # 最弱文字
LINE = "#e3e9f2"         # 分隔线
LINE_SOFT = "#eef2f8"    # 表格网格
CANVAS = "#f4f7fc"       # 窗口底色
SURFACE = "#ffffff"      # 卡片底色
ACCENT = "#2f6bdb"
ACCENT_DARK = "#2559bd"
ACCENT_SOFT = "#eaf1fe"
SUCCESS = "#0f8a5f"
WARN = "#b87410"
DANGER = "#c2402f"
SIDEBAR_TOP = "#0d1930"
SIDEBAR_BOTTOM = "#182740"

# ---------------------------------------------------------------- 图标
# 24x24 线性图标，stroke 由渲染时传入的颜色决定
ICONS = {
    "dashboard": '<rect x="3.4" y="3.4" width="7.2" height="7.6" rx="2.2"/>'
                 '<rect x="13.4" y="3.4" width="7.2" height="4.6" rx="2.2"/>'
                 '<rect x="13.4" y="10.8" width="7.2" height="9.8" rx="2.2"/>'
                 '<rect x="3.4" y="13.8" width="7.2" height="6.8" rx="2.2"/>',
    "orders": '<rect x="5.6" y="4.4" width="12.8" height="16.2" rx="2.6"/>'
              '<path d="M9.4 4.4v-.6a1.4 1.4 0 0 1 1.4-1.4h2.4a1.4 1.4 0 0 1 1.4 1.4v.6"/>'
              '<path d="M9 10h6"/><path d="M9 14h3.6"/>',
    "package": '<path d="M12 3.2 20 7.6v8.8L12 20.8 4 16.4V7.6z"/>'
               '<path d="M4 7.6 12 12l8-4.4"/><path d="M12 12v8.8"/>',
    "daily": '<rect x="3.4" y="3.4" width="17.2" height="17.2" rx="4.2"/>'
             '<path d="m8 12.3 2.9 2.9L16.5 9.4"/>',
    "gear": '<circle cx="12" cy="12" r="3.1"/>'
            '<path d="M19.6 14.6a1.5 1.5 0 0 0 .3 1.7l.1.1a1.9 1.9 0 1 1-2.7 2.7l-.1-.1a1.5 1.5 0 0 0-2.5 1v.2a1.9 1.9 0 1 1-3.8 0v-.1a1.5 1.5 0 0 0-2.6-1l-.1.1a1.9 1.9 0 1 1-2.7-2.7l.1-.1a1.5 1.5 0 0 0-1-2.5H4.4a1.9 1.9 0 1 1 0-3.8h.1a1.5 1.5 0 0 0 1-2.6l-.1-.1a1.9 1.9 0 1 1 2.7-2.7l.1.1a1.5 1.5 0 0 0 2.5-1V4.4a1.9 1.9 0 1 1 3.8 0v.1a1.5 1.5 0 0 0 2.5 1l.1-.1a1.9 1.9 0 1 1 2.7 2.7l-.1.1a1.5 1.5 0 0 0 1 2.5h.2a1.9 1.9 0 1 1 0 3.8h-.1a1.5 1.5 0 0 0-1.1.6z"/>',
    "alert": '<path d="M12 3.8 21 19.6H3z"/><path d="M12 9.6v4.2"/><path d="M12 17h.01"/>',
    "clock": '<circle cx="12" cy="12" r="8.6"/><path d="M12 7.4V12l3.1 1.9"/>',
    "activity": '<path d="M3.4 12.6h3.9l2.4-6.2 4 12.2 2.5-6h4.4"/>',
    "inbox": '<path d="M3.4 13.2 6 5.2h12l2.6 8v4.6a1.8 1.8 0 0 1-1.8 1.8H5.2a1.8 1.8 0 0 1-1.8-1.8z"/>'
             '<path d="M3.4 13.2h4l1.4 2.4h6.4l1.4-2.4h4"/>',
    "search": '<circle cx="10.8" cy="10.8" r="6.4"/><path d="m15.6 15.6 4.2 4.2"/>',
    "plus": '<path d="M12 5.2v13.6"/><path d="M5.2 12h13.6"/>',
    "import": '<path d="M12 3.6v9.8"/><path d="m8.2 9.8 3.8 3.6 3.8-3.6"/>'
              '<path d="M4.6 15.6v3a1.9 1.9 0 0 0 1.9 1.9h11a1.9 1.9 0 0 0 1.9-1.9v-3"/>',
    "template": '<rect x="4.4" y="3.4" width="15.2" height="17.2" rx="2.6"/>'
                '<path d="M8.4 8.6h7.2"/><path d="M8.4 12.6h7.2"/><path d="M8.4 16.6h4"/>',
    "database": '<ellipse cx="12" cy="6.4" rx="7.4" ry="3"/>'
                '<path d="M4.6 6.4v11.2c0 1.66 3.31 3 7.4 3s7.4-1.34 7.4-3V6.4"/>'
                '<path d="M4.6 12c0 1.66 3.31 3 7.4 3s7.4-1.34 7.4-3"/>',
    "folder": '<path d="M3.6 7.2a2 2 0 0 1 2-2h3.6l2 2.4h7.2a2 2 0 0 1 2 2v8.2a2 2 0 0 1-2 2H5.6a2 2 0 0 1-2-2z"/>',
    "refresh": '<path d="M20.2 12a8.2 8.2 0 1 1-2.6-6"/><path d="M20.2 4.4v4.8h-4.8"/>',
    "external": '<path d="M14.2 4.4h5.4v5.4"/><path d="M19.6 4.4 11 13"/>'
                '<path d="M18 15.4v3.2a2 2 0 0 1-2 2H5.6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h3.2"/>',
    "calendar": '<rect x="3.6" y="5.4" width="16.8" height="15.2" rx="2.8"/>'
                '<path d="M3.6 10.4h16.8"/><path d="M8.4 3.4v4"/><path d="M15.6 3.4v4"/>',
    "check": '<path d="m5 12.6 4.6 4.6L19 7.6"/>',
    "spark": '<path d="M12 3.4 13.9 9l5.7 1.9-5.7 1.9L12 18.4l-1.9-5.6L4.4 10.9 10.1 9z"/>',
    "export": '<path d="M12 16.4V6.6"/><path d="m8.2 10.4 3.8-3.8 3.8 3.8"/>'
              '<path d="M4.6 15.6v3a1.9 1.9 0 0 0 1.9 1.9h11a1.9 1.9 0 0 0 1.9-1.9v-3"/>',
}


def svg_markup(name, color=INK, size=18, width=1.8):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="{size}" height="{size}" '
            f'fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round">'
            f'{ICONS[name]}</svg>')


def icon(name, color=INK, size=18, width=1.8):
    """把 SVG 渲染成 2 倍图的高清 QIcon。"""
    renderer = QSvgRenderer(QByteArray(svg_markup(name, color, size, width).encode("utf-8")))
    pixmap = QPixmap(QSize(int(size * 2), int(size * 2)))
    pixmap.setDevicePixelRatio(2.0)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return QIcon(pixmap)


def pixmap(name, color=INK, size=18, width=1.8):
    return icon(name, color, size, width).pixmap(QSize(int(size), int(size)))


def brand_mark(size=34):
    """侧边栏品牌标记：圆角渐变底 + 白色「单」字。"""
    scale = 2.0
    pixmap = QPixmap(QSize(int(size * scale), int(size * scale)))
    pixmap.setDevicePixelRatio(scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0.0, QColor("#4d8bf5"))
    gradient.setColorAt(1.0, QColor(ACCENT_DARK))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(QRectF(0, 0, size, size), size * 0.3, size * 0.3)
    painter.setPen(QColor("#ffffff"))
    font = QFont("Microsoft YaHei UI", int(size * 0.46), QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(QRectF(0, -size * 0.02, size, size), Qt.AlignmentFlag.AlignCenter, "单")
    painter.end()
    return pixmap


def app_icon():
    """程序 / 托盘图标。"""
    return QIcon(brand_mark(64))


def _asset(name, size, draw):
    """样式表里用到的小图标写成 PNG 缓存，避免依赖 SVG 图像插件。"""
    folder = Path(tempfile.gettempdir()) / "order-followup-theme"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{name}.png"
    if not target.exists():
        image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        draw(painter, size)
        painter.end()
        image.save(str(target))
    return target.as_posix()


def _check_asset():
    def draw(painter, size):
        pen = QPen(QColor("#ffffff"))
        pen.setWidthF(size * 0.11)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline(QPolygonF([QPointF(size * 0.24, size * 0.53),
                                        QPointF(size * 0.43, size * 0.72),
                                        QPointF(size * 0.77, size * 0.31)]))
    return _asset("check", 36, draw)


def _chevron_asset():
    def draw(painter, size):
        pen = QPen(QColor("#7a879b"))
        pen.setWidthF(size * 0.13)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline(QPolygonF([QPointF(size * 0.28, size * 0.4),
                                        QPointF(size * 0.5, size * 0.62),
                                        QPointF(size * 0.72, size * 0.4)]))
    return _asset("chevron", 28, draw)


# ---------------------------------------------------------------- 绘制代理
BADGES = {
    "紧急": (DANGER, "#fdecea"),
    "高": (WARN, "#fdf3e2"),
    "待跟进": (ACCENT, "#eaf1fe"),
    "正常": (INK_SOFT, "#eef2f8"),
    "已完成": (SUCCESS, "#e7f6ef"),
}
DOTS = {
    "已确认": SUCCESS,
    "待确认": WARN,
    "完成": SUCCESS,
    "进行中": ACCENT,
    "无需跟进": SUCCESS,
    "需要跟进": DANGER,
    "已处理": ACCENT,
    "待检查": FAINT,
}


class BadgeDelegate(QStyledItemDelegate):
    """把「紧急 / 高 / 正常」之类画成胶囊标签。"""

    def paint(self, painter, option, index):
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        palette = BADGES.get(text)
        if not palette:
            super().paint(painter, option, index)
            return
        base = QStyleOptionViewItem(option)
        self.initStyleOption(base, index)
        base.text = ""
        widget = base.widget
        (widget.style() if widget else QApplication.style()).drawControl(
            QStyle.ControlElement.CE_ItemViewItem, base, painter, widget)
        foreground, background = palette
        font = QFont(option.font)
        font.setPointSizeF(option.font.pointSizeF() - 1.2)
        font.setBold(True)
        metrics = QFontMetrics(font)
        width = metrics.horizontalAdvance(text) + 20
        height = 21.0
        rect = QRectF(option.rect.left() + 8, option.rect.center().y() - height / 2 + 0.5, width, height)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(rect, height / 2, height / 2)
        painter.setPen(QColor(foreground))
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()


class StatusDelegate(QStyledItemDelegate):
    """状态列：小圆点 + 文字。"""

    def paint(self, painter, option, index):
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        color = DOTS.get(text)
        if not color:
            super().paint(painter, option, index)
            return
        base = QStyleOptionViewItem(option)
        self.initStyleOption(base, index)
        base.text = ""
        widget = base.widget
        (widget.style() if widget else QApplication.style()).drawControl(
            QStyle.ControlElement.CE_ItemViewItem, base, painter, widget)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(QPointF(option.rect.left() + 13, option.rect.center().y()), 3.2, 3.2)
        painter.setPen(QColor(color if color != WARN else "#9a6410"))
        painter.drawText(QRectF(option.rect.left() + 22, option.rect.top(), option.rect.width() - 24, option.rect.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        painter.restore()


class ProgressDelegate(QStyledItemDelegate):
    """确认进度：细进度条 + 分数文字。"""

    def paint(self, painter, option, index):
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        if "/" not in text:
            super().paint(painter, option, index)
            return
        try:
            done, total = (int(part) for part in text.split("/", 1))
        except ValueError:
            super().paint(painter, option, index)
            return
        base = QStyleOptionViewItem(option)
        self.initStyleOption(base, index)
        base.text = ""
        widget = base.widget
        (widget.style() if widget else QApplication.style()).drawControl(
            QStyle.ControlElement.CE_ItemViewItem, base, painter, widget)
        ratio = (done / total) if total else 0.0
        color = SUCCESS if done == total and total else (FAINT if done == 0 else ACCENT)
        track = QRectF(option.rect.left() + 8, option.rect.center().y() - 3, 34, 6)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#edf1f7"))
        painter.drawRoundedRect(track, 3, 3)
        if ratio > 0:
            fill = QRectF(track.left(), track.top(), max(6.0, track.width() * ratio), track.height())
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(fill, 3, 3)
        font = QFont(option.font)
        font.setPointSizeF(option.font.pointSizeF() - 1.0)
        painter.setFont(font)
        painter.setPen(QColor(INK_SOFT if color != FAINT else FAINT))
        painter.drawText(QRectF(track.right() + 7, option.rect.top(), option.rect.width() - 50, option.rect.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        painter.restore()


# ---------------------------------------------------------------- 样式表
_STYLE = '''
QWidget { font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"; font-size: 13px; color: #16202f; }
QMainWindow, QDialog { background: #f4f7fc; }
QToolTip { background: #16202f; color: #ffffff; border: none; padding: 6px 9px; border-radius: 6px; font-size: 12px; }

/* ---------- 侧边栏 ---------- */
QWidget#sidebar { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0d1930, stop:1 #182740); }
QLabel#brandName { color: #ffffff; font-size: 14.5px; font-weight: 600; }
QLabel#brandMeta { color: #7e90ad; font-size: 11px; }
QLabel#sideFoot { color: #7186a6; font-size: 11px; }
QLabel#sideFootTitle { color: #9db0cc; font-size: 11.5px; font-weight: 600; }
QFrame#sideLine { background: #22334e; border: none; }
QFrame#sideCard { background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px; }
QLabel#sideCardTitle { color: #e8effa; font-size: 12.5px; font-weight: 600; }
QLabel#sideCardMeta { color: #8fa3c0; font-size: 11px; }
QListWidget#nav { background: transparent; border: none; outline: none; padding: 0 10px; }
QListWidget#nav::item { color: #a9bad3; padding: 0 12px; margin: 2px 0; border-radius: 9px; font-size: 13.5px; }
QListWidget#nav::item:hover { background: rgba(255, 255, 255, 0.06); color: #e8effa; }
QListWidget#nav::item:selected { background: rgba(74, 131, 240, 0.22); color: #ffffff; }

/* ---------- 文字层级 ---------- */
QLabel#title { font-size: 21px; font-weight: 600; color: #101b2b; }
QLabel#subtitle { color: #6b7891; font-size: 12px; }
QLabel#section { font-size: 13.5px; font-weight: 600; color: #1b2a40; }
QLabel#meta { color: #98a4b7; font-size: 11.5px; }
QLabel#muted { color: #6b7891; font-size: 12px; }
QLabel#fieldLabel { color: #6b7891; font-size: 11.5px; }
QLabel#stat { font-size: 27px; font-weight: 600; color: #101b2b; }
QLabel#dialogTitle { font-size: 17px; font-weight: 600; color: #101b2b; }
QLabel#hint { color: #6b7891; font-size: 11.5px; }

/* ---------- 卡片 ---------- */
QFrame#card { background: #ffffff; border: 1px solid #e3e9f2; border-radius: 14px; }
QFrame#inner { background: #f8fafd; border: 1px solid #e7edf6; border-radius: 10px; }
QFrame#divider { background: #eef2f8; border: none; }
QFrame#accentChip { border: none; border-radius: 11px; }

/* ---------- 按钮 ---------- */
QPushButton { background: #ffffff; border: 1px solid #dbe3ef; border-radius: 8px; padding: 7px 14px;
              color: #24344c; font-size: 12.5px; }
QPushButton:hover { background: #f2f6fd; border-color: #b9c9e2; }
QPushButton:pressed { background: #e8eefa; }
QPushButton:disabled { color: #a3aec0; background: #f4f6fa; border-color: #e8edf5; }
QPushButton#primary { background: #2f6bdb; border-color: #2f6bdb; color: #ffffff; font-weight: 600; }
QPushButton#primary:hover { background: #2559bd; border-color: #2559bd; }
QPushButton#primary:pressed { background: #1f4da5; }
QPushButton#primary:disabled { background: #aec5ea; border-color: #aec5ea; color: #f2f6ff; }
QPushButton#ghost { background: transparent; border-color: transparent; color: #2f6bdb; }
QPushButton#ghost:hover { background: #eaf1fe; border-color: transparent; }
QPushButton#tool { padding: 6px 11px; font-size: 12px; border-radius: 7px; }
QPushButton#danger { color: #c2402f; }
QPushButton#danger:hover { background: #fdeeec; border-color: #f0c4bd; }

/* ---------- 输入 ---------- */
QLineEdit, QComboBox, QDateEdit, QDateTimeEdit, QTextEdit, QPlainTextEdit {
    background: #ffffff; border: 1px solid #dbe3ef; border-radius: 8px; padding: 6px 10px;
    color: #16202f; selection-background-color: #2f6bdb; selection-color: #ffffff; }
QLineEdit:hover, QComboBox:hover, QDateEdit:hover, QDateTimeEdit:hover, QTextEdit:hover { border-color: #c3d1e6; }
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QDateTimeEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border: 1px solid #2f6bdb; background: #ffffff; }
QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled { background: #f5f7fb; color: #9aa6b8; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right; width: 22px; border: none; }
QComboBox::down-arrow { image: url(__ASSETS__/chevron.png); width: 11px; height: 11px; }
QDateEdit::up-button, QDateEdit::down-button, QDateTimeEdit::up-button, QDateTimeEdit::down-button {
    width: 0; height: 0; border: none; background: transparent; }
QDateEdit, QDateTimeEdit { padding-right: 26px; }
QDateEdit::drop-down, QDateTimeEdit::drop-down { subcontrol-origin: padding; subcontrol-position: center right;
    width: 22px; border: none; background: transparent; }
QDateEdit::down-arrow, QDateTimeEdit::down-arrow { image: url(__ASSETS__/chevron.png); width: 11px; height: 11px; }
QComboBox QAbstractItemView { background: #ffffff; border: 1px solid #dbe3ef; border-radius: 8px;
    padding: 4px; outline: none; selection-background-color: #eaf1fe; selection-color: #1b2a40; }
QComboBox QAbstractItemView::item { min-height: 26px; padding: 2px 6px; border-radius: 6px; }

/* ---------- 表格 ---------- */
QTableWidget { background: #ffffff; alternate-background-color: #ffffff; border: none; gridline-color: #eef2f8;
    selection-background-color: #eff4ff; selection-color: #16202f; outline: none; }
QTableWidget::item { padding: 0 6px; border: none; }
QTableWidget::item:hover { background: #f8fbff; }
QTableWidget::item:selected { background: #dce9ff; color: #16202f; }
QTableWidget::indicator { width:17px; height:17px; border:2px solid #7d90ac; border-radius:4px; background:#ffffff; }
QTableWidget::indicator:checked { background:#245dce; border-color:#245dce; image:url(__ASSETS__/check.png); }
QHeaderView { background: transparent; }
QHeaderView::section { background: #f8fafd; color: #6b7891; padding: 0 6px; border: none;
    border-bottom: 1px solid #e3e9f2; font-size: 11.5px; font-weight: 600; }
QHeaderView::section:hover { background: #f1f5fb; }
QTableCornerButton::section { background: #f8fafd; border: none; border-bottom: 1px solid #e3e9f2; }

/* ---------- 拖拽导入遮罩 ---------- */
QFrame#dropOverlay { background: rgba(250, 252, 255, 0.97); border: 2px dashed #2f6bdb; border-radius: 18px; }
QLabel#dropTitle { font-size: 21px; font-weight: 700; color: #16233a; }
QLabel#dropHint { font-size: 12.5px; color: #64748b; }

/* ---------- 标签页 ---------- */
QTabWidget::pane { border: none; background: transparent; }
QTabWidget::tab-bar { left: 0; }
QTabBar { qproperty-drawBase: 0; }
QTabBar::tab { background: transparent; color: #6b7891; padding: 8px 15px; margin-right: 4px;
    border-radius: 8px; font-size: 12.5px; }
QTabBar::tab:hover { background: #eef3fb; color: #24344c; }
QTabBar::tab:selected { background: #eaf1fe; color: #2f6bdb; font-weight: 600; }

/* ---------- 复选 / 滚动条 ---------- */
QCheckBox { spacing: 8px; color: #24344c; font-size: 12.5px; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #c8d4e6; border-radius: 5px; background: #ffffff; }
QCheckBox::indicator:hover { border-color: #2f6bdb; }
QCheckBox::indicator:checked { background: #2f6bdb; border-color: #2f6bdb; image: url(__ASSETS__/check.png); }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px 2px 2px 0; }
QScrollBar::handle:vertical { background: #d3dded; border-radius: 4px; min-height: 36px; }
QScrollBar::handle:vertical:hover { background: #b7c7de; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0 2px 2px 2px; }
QScrollBar::handle:horizontal { background: #d3dded; border-radius: 4px; min-width: 36px; }
QScrollBar::handle:horizontal:hover { background: #b7c7de; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* ---------- 其他 ---------- */
QFrame#statusStrip { background: #f7f9fd; border: none; border-top: 1px solid #e3e9f2; }
QLabel#statusText { color: #8592a6; font-size: 11.5px; }
QLabel#navCaption { color: #5f7492; font-size: 10.5px; font-weight: 600; letter-spacing: 1px; }
QMenu { background: #ffffff; border: 1px solid #e3e9f2; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 7px 22px 7px 14px; border-radius: 6px; color: #24344c; }
QMenu::item:selected { background: #eaf1fe; color: #1b2a40; }
QMenu::separator { height: 1px; background: #eef2f8; margin: 5px 8px; }
QDialogButtonBox QPushButton { min-width: 68px; }
QSplitter::handle { background: #eef2f8; }
'''


def stylesheet():
    assets = Path(_check_asset()).parent.as_posix()
    _chevron_asset()
    return _STYLE.replace("__ASSETS__", assets)


STYLE = stylesheet()


def export_scope_stylesheet():
    """导出窗口独立指定明暗状态，避免 Windows 深色原生控件混入。"""
    assets=Path(_check_asset()).parent.as_posix()
    return '''
QDialog#exportScopeDialog { background:#f4f7fc; color:#16202f; }
QDialog#exportScopeDialog QLabel { color:#24344c; background:transparent; }
QDialog#exportScopeDialog QRadioButton { color:#16202f; background:transparent; spacing:9px; padding:4px 0; }
QDialog#exportScopeDialog QRadioButton::indicator { width:18px; height:18px; border:2px solid #7d90ac; border-radius:11px; background:#ffffff; }
QDialog#exportScopeDialog QRadioButton::indicator:checked { border-color:#245dce;
 background:qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5, stop:0 #245dce, stop:0.55 #245dce, stop:0.6 #ffffff, stop:1 #ffffff); }
QListWidget#exportSheetList { background:#ffffff; alternate-background-color:#ffffff; color:#16202f;
 border:1px solid #b8c7dd; border-radius:8px; padding:4px; outline:none; selection-background-color:#e7efff; selection-color:#16202f; }
QListWidget#exportSheetList:disabled { background:#f6f8fb; color:#53657d; }
QListWidget#exportSheetList::item { color:#16202f; min-height:28px; padding:4px 8px; border:1px solid transparent; border-radius:5px; }
QListWidget#exportSheetList::item:hover { background:#f1f5fd; }
QListWidget#exportSheetList::item:selected { color:#16202f; background:#e7efff; border-color:#87aef0; }
QListWidget#exportSheetList::item:disabled { color:#53657d; background:#f6f8fb; }
QListWidget#exportSheetList::indicator { width:18px; height:18px; border:2px solid #7d90ac; border-radius:4px; background:#ffffff; }
QListWidget#exportSheetList::indicator:checked { background:#245dce; border-color:#245dce; image:url(__ASSETS__/check.png); }
QListWidget#exportSheetList::indicator:checked:disabled { background:#647b9b; border-color:#647b9b; image:url(__ASSETS__/check.png); }
QListWidget#exportSheetList::indicator:unchecked:disabled { background:#ffffff; border-color:#91a0b5; }
QLabel#exportSelectionSummary { color:#174da5; font-weight:600; }
QLabel#exportSelectionHint { color:#53657d; }
'''.replace('__ASSETS__',assets)
