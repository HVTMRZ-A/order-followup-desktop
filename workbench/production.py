"""生产作业计划单（整机生产单）解析与计划总表映射。

设计原则：
1. 不按固定单元格坐标取值，按"标签 / 表头文字"定位，行位置漂移也能认出来；
2. 认不准的一律留空并写入 warnings，绝不猜数值；
3. 解析只读源文件，不回写。
"""
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .domain import fmt, new_item, new_order, number, uid

# ---------------------------------------------------------------- 计划总表列
# 与《2026年新能源新计划.xlsx》"最新"表 A:AL 完全一致
PLAN_COLUMNS = [
    "计划序列号", "客订编号", "业务员", "订单号", "物料编码", "类别", "规格型号", "产品型号",
    "电压(V)", "频率(Hz)", "功率(W)", "订单数量", "未完工数量", "完工数量", "发货数量",
    "库存数量未发货", "接单日期", "客户交期", "生产单交期", "受订日期", "自制/外购",
    "分析时间", "运算编号", "派工日期", "派工数量", "签字下发", "总装生产时间",
    "包材资料下发日期", "包材采购时间", "请购单号", "备注", "丝印", "铭牌", "纸箱",
    "说明书", "流水号", "标贴", "运行状态",
]

# 表头别名 → 明细行字段
ITEM_HEADERS = {
    "序号": "seq",
    "产品大类": "category",
    "产品类别": "category",
    "客户型号": "customer_model",
    "公司型号": "model",
    "产品型号": "model",
    "数量": "quantity",
    "单位": "unit",
    "产品要求": "requirement",
    "产品说明": "requirement",
    "包材": "packaging",
    "bom状态": "bom_status",
    "bom": "bom_status",
    "物料代码": "material_code",
    "物料编码": "material_code",
}

# 头部标签 → 订单字段
HEADER_LABELS = {
    "合同编号": "number",
    "订单号": "number",
    "客户编号": "customer_no",
    "客户": "customer_no",
    "计划完成日期": "delivery_date",
    "订单属性": "attribute",
    "数量": "declared_quantity",
    "总数量": "declared_quantity",
    "运输方式": "transport",
    "经办人": "owner",
    "下单日期": "received_at",
    "接单日期": "received_at",
    "注意事项": "notes",
}

TAIL_WORDS = ("注意事项", "复核", "批准", "审批", "编制", "审核", "下单日期")

# 类别 → 自制/外购 的保守推断，仅作默认值，导入时提示核对
PURCHASED_HINTS = ("逆变器-外", "储能逆变器", "空壳机", "外购")


# ---------------------------------------------------------------- 基础取值
def _text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return re.sub(r"\s+", " ", str(value)).strip()


def _raw(value):
    """保留内部换行的原始文本（规格型号需要换行）。"""
    if value is None:
        return ""
    return str(value).strip()


def as_date(value):
    """把 datetime / date / Excel 序列号 / 常见字符串统一成 date。"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        serial = float(value)
        if 20000 <= serial <= 80000:  # Excel 1900 日期系统合理区间
            return date(1899, 12, 30) + timedelta(days=int(serial))
        raise ValueError(f"无法识别的日期序列号：{value}")
    text = _text(value)
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass
    text = re.sub(r"[年月]", "-", text).replace("日", "").replace(".", "-").replace("/", "-")
    text = text.split(" ")[0]
    for pattern in ("%Y-%m-%d", "%Y-%m", "%Y%m%d"):
        try:
            parsed = datetime.strptime(text, pattern).date()
            return parsed
        except ValueError:
            continue
    raise ValueError(f"无法识别的日期：{value}")


def as_number(value):
    if value is None or _text(value) == "":
        return None
    try:
        return Decimal(_text(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


# ---------------------------------------------------------------- 表结构识别
def _scan_rows(path, limit=200, max_col=40):
    from openpyxl import load_workbook

    book = load_workbook(path, read_only=True, data_only=True)
    try:
        found = []
        for sheet in book.worksheets:
            rows = []
            for index, row in enumerate(sheet.iter_rows(max_row=limit, max_col=max_col), 1):
                rows.append([cell.value for cell in row])
            found.append((sheet.title, rows))
        return found
    finally:
        book.close()


def _header_map(row):
    """把一行当表头解析，命中的字段不足则返回空。"""
    mapping = {}
    for index, cell in enumerate(row):
        key = re.sub(r"[\s\n]+", "", _text(cell)).lower()
        if not key:
            continue
        if key in ITEM_HEADERS:
            field = ITEM_HEADERS[key]
            mapping.setdefault(field, index)
    if "model" in mapping and "quantity" in mapping:
        return mapping
    return {}


def is_production_sheet(path):
    """粗判：任意工作表前若干行存在「公司型号 / 产品型号 + 数量」表头。"""
    if Path(path).suffix.lower() not in (".xlsx", ".xlsm"):
        return False
    try:
        for _, rows in _scan_rows(path, limit=200,max_col=300):
            for row in rows:
                if _header_map(row) and '订单号' not in [_text(v) for v in row]:
                    return True
    except Exception:
        return False
    return False


def _parse_header_fields(rows, header_row):
    """头部区域（表头行以上）按「标签 → 右侧单元格」取值。"""
    fields, spans = {}, []
    for row_index, row in enumerate(rows):
        if row_index == header_row:
            break
        for index, cell in enumerate(row):
            text = _text(cell)
            if not text:
                continue
            probe = re.sub(r"[\s\n]+", "", text).rstrip("：:")
            matched = None
            for label, field in HEADER_LABELS.items():
                if probe == label:
                    matched = field
                    break
            if matched is None:
                for label, field in HEADER_LABELS.items():
                    if probe.startswith(label) and len(probe) > len(label):
                        # 「合同编号：26LTJX2043」同格写法
                        rest = probe[len(label):].lstrip("：:")
                        if rest and field not in fields:
                            fields[field] = rest
                            spans.append((row_index, index))
                        matched = field
                        break
                continue
            if matched in fields:
                continue
            for right in range(index + 1, len(row)):
                value = row[right]
                if _text(value):
                    fields[matched] = value
                    spans.append((row_index, index))
                    break
    return fields, spans


def _merge_cell_text(rows, header_row):
    """表头以上的标题文字（如「2026年10月份生产作业计划单」），只留标题口径。"""
    parts = []
    for row_index, row in enumerate(rows):
        if row_index >= header_row:
            break
        for cell in row:
            text = _text(cell)
            if not text or text.endswith("：") or text.endswith(":"):
                continue
            if ("月" in text or "生产" in text or "计划单" in text) and len(text) <= 40:
                parts.append(text)
    return parts


def _tail_fields(rows, last_item_row):
    """表头以下、明细行之后的「复核 / 批准 / 经办人 / 下单日期」。"""
    fields = {}
    for row in rows[last_item_row + 1:]:
        for index, cell in enumerate(row):
            probe = re.sub(r"[\s\n]+", "", _text(cell)).rstrip("：:")
            for label, field in (("经办人", "owner"), ("下单日期", "received_at")):
                if probe == label:
                    for right in range(index + 1, len(row)):
                        if _text(row[right]):
                            fields[field] = row[right]
                            break
    return fields


# ---------------------------------------------------------------- 主解析
def read_production(path, existing_numbers=()):
    """解析一份生产作业计划单，返回订单 dict 列表（通常 1 个）。"""
    path = Path(path)
    if path.suffix.lower() not in (".xlsx", ".xlsm"):
        raise ValueError("生产单请使用 .xlsx 格式；旧版 .xls 请先另存为 .xlsx")

    from .planbook import read_planbook
    from openpyxl.utils.cell import coordinate_to_tuple
    snapshot,_=read_planbook(path)
    grids=[]
    for sheet in snapshot['sheets']:
        if sheet['rows']>10000:raise ValueError('生产单超过 10000 行，请拆分；未执行截断导入。')
        rows=[['']*sheet['cols'] for _ in range(sheet['rows'])]
        for address,cell in sheet['cells'].items():
            r,c=coordinate_to_tuple(address);rows[r-1][c-1]=cell.get('v')
        grids.append((sheet['name'],rows))
    warnings = []
    for sheet_name, rows in grids:
        header_row = next((i for i, row in enumerate(rows) if _header_map(row)), None)
        if header_row is None:
            continue
        columns = _header_map(rows[header_row])
        head, _ = _parse_header_fields(rows, header_row)
        items, last_row = [], header_row
        for row_index in range(header_row + 1, len(rows)):
            row = rows[row_index]
            first = _text(row[0]) if row else ""
            if any(word in first for word in TAIL_WORDS):
                break
            model = _text(row[columns["model"]]) if columns["model"] < len(row) else ""
            quantity = as_number(row[columns["quantity"]]) if columns["quantity"] < len(row) else None
            if not model and quantity is None:
                continue
            if not model or quantity is None:
                warnings.append(f"第 {row_index + 1} 行型号或数量不完整，已跳过")
                continue
            if quantity <= 0:
                warnings.append(f"第 {row_index + 1} 行数量为 {fmt(quantity)}，已跳过")
                continue
            item = dict(model=model, quantity=fmt(quantity))
            item['source_columns']={str(h).strip():_raw(v) for h,v in zip(rows[header_row],row) if h is not None and str(h).strip()}
            for field, index in columns.items():
                if field in ("model", "quantity") or index >= len(row):
                    continue
                raw = _raw(row[index])
                if not raw:
                    continue
                if field == "packaging":
                    # 生产单的「包材」是供应商名（绿田），不能覆盖工作台的包材确认布尔位
                    item["packaging_name"] = _text(raw)
                elif field == "requirement":
                    item["requirement"] = raw
                else:
                    item[field] = _text(raw)
            items.append(item)
            last_row = row_index
        if not items:
            continue

        head.update({k: v for k, v in _tail_fields(rows, last_row).items() if v and k not in head})
        titles = _merge_cell_text(rows, header_row)
        return [_build_order(path, sheet_name, titles, head, items, warnings, existing_numbers)]
    raise ValueError("没有识别到生产单明细表头（需要包含「公司型号」和「数量」列）；"
                     "如果是导入模板，请改用模板格式")


def _build_order(path, sheet_name, titles, head, items, warnings, existing_numbers):
    order = new_order()
    order["number"] = _text(head.get("number"))
    if not order["number"]:
        raise ValueError("生产单没有识别到合同编号 / 订单号")
    if order["number"] in set(existing_numbers):
        raise ValueError(f"订单 {order['number']} 已存在，请在订单详情中修改")

    order["customer_no"] = _text(head.get("customer_no"))
    order["owner"] = _text(head.get("owner"))
    order["transport"] = _text(head.get("transport"))
    order["attribute"] = _text(head.get("attribute"))
    order["notes"] = _text(head.get("notes"))
    order["source_file"] = Path(path).name
    order["source_sheet"] = sheet_name
    order["source_titles"] = titles
    order["month"] = _month_from_titles(titles, head)

    try:
        received = as_date(head.get("received_at"))
    except ValueError as exc:
        warnings.append(str(exc))
        received = None
    order["received_at"] = (received or date.today()).isoformat() + "T00:00:00"
    try:
        delivery = as_date(head.get("delivery_date"))
        order["delivery_date"] = delivery.isoformat() if delivery else ""
    except ValueError as exc:
        warnings.append(f"计划完成日期：{exc}")
        order["delivery_date"] = ""
    # 生产单的「计划完成日期」在总表里对应「生产单交期」，单独留一份避免与客户交期混淆
    order["plan_delivery_date"] = order["delivery_date"]

    declared = as_number(head.get("declared_quantity"))
    total = sum(Decimal(i["quantity"]) for i in items)
    if declared is not None and declared != total:
        warnings.append(f"表头数量 {fmt(declared)} 与明细合计 {fmt(total)} 不一致，请核对")

    merged, seen = [], {}
    for item in items:
        key = (item["model"], item.get("material_code", ""))
        if key in seen:
            target = seen[key]
            target["quantity"] = fmt(Decimal(target["quantity"]) + Decimal(item["quantity"]))
            target.setdefault('source_rows',[]).append(item.get('source_columns',{}))
            warnings.append(f"型号 {item['model']} 出现多行，已合并数量")
            continue
        new = new_item(item["model"], item["quantity"])
        new.update({k: v for k, v in item.items() if k not in ("model", "quantity")})
        new["id"] = uid()
        new['source_rows']=[item.get('source_columns',{})]
        seen[key] = new
        merged.append(new)
    order["items"] = merged
    order["warnings"] = warnings
    return order


def _month_from_titles(titles, head):
    for text in titles:
        matched = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月", text)
        if matched:
            return f"{matched.group(1)}-{int(matched.group(2)):02d}"
    received = head.get("received_at")
    try:
        value = as_date(received)
    except ValueError:
        value = None
    return value.strftime("%Y-%m") if value else ""


# ---------------------------------------------------------------- 总表映射
VOLT_RE = re.compile(r"(\d{2,3}(?:\s*[-~/]\s*\d{2,3})*)\s*V(?:AC|ac|AC/DC)?(?![a-zA-Z])")
FREQ_RE = re.compile(r"(\d{2,3}(?:\s*/\s*\d{2,3})*)\s*Hz", re.IGNORECASE)
POWER_RE = re.compile(r"(?:输出功率|额定功率|总功率|功率)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(kW|KW|kw|W|w)?")
KW_RE = re.compile(r"(?<![A-Za-z])(\d+(?:\.\d+)?)\s*(kW|KW|kw)(?![A-Za-z])")
BARE_W_RE = re.compile(r"(?<![\d.])(\d{2,6})\s*W(?![A-Za-z])")


def extract_ratings(text):
    """从规格 / 产品要求文本里取电压、频率、功率，取不到就留空。"""
    text = _text(text)
    voltage = frequency = power = None
    if not text:
        return voltage, frequency, power
    matched = VOLT_RE.search(text)
    if matched:
        voltage = re.sub(r"\s+", "", matched.group(1))
    matched = FREQ_RE.search(text)
    if matched:
        frequency = re.sub(r"\s+", "", matched.group(1))
    matched = POWER_RE.search(text)
    if matched and matched.group(2) and matched.group(2).lower() == "kw":
        power = int(Decimal(matched.group(1)) * 1000)
    elif matched and matched.group(2):
        power = int(Decimal(matched.group(1)))
    else:
        matched = KW_RE.search(text)
        if matched:
            power = int(Decimal(matched.group(1)) * 1000)
        else:
            matched = BARE_W_RE.search(text)
            if matched:
                power = int(matched.group(1))
    return voltage, frequency, power


def _supply_kind(category, model):
    text = f"{category}{model}"
    return "外购" if any(hint in text for hint in PURCHASED_HINTS) else "自制"


def _date_text(value):
    if not value:
        return ""
    try:
        return as_date(value).isoformat()
    except ValueError:
        return ""


def plan_rows(order, serial=""):
    """把一个订单展开成计划总表的行（每型号一行），并返回待核对项。"""
    base_notes = []
    if order.get("attribute"):
        base_notes.append(f"订单属性：{order['attribute']}")
    if order.get("transport"):
        base_notes.append(f"运输方式：{order['transport']}")
    if order.get("notes"):
        base_notes.append(order["notes"])
    base_note = "；".join(part for part in base_notes if part)
    rows, warnings = [], []
    for index, item in enumerate(order.get("items", [])):
        requirement = item.get("requirement", "")
        voltage, frequency, power = extract_ratings(requirement)
        notes = [base_note] if base_note else []
        if item.get("customer_model"):
            notes.append(f"客户型号：{item['customer_model']}")
        if item.get("packaging_name"):
            notes.append(f"包材：{item['packaging_name']}")
        if item.get("bom_status"):
            notes.append(f"BOM状态：{item['bom_status']}")
        if item.get("unit"):
            notes.append(f"单位：{item['unit']}")
        row = dict.fromkeys(PLAN_COLUMNS, "")
        row.update({
            "计划序列号": serial if index == 0 else "",
            "客订编号": order.get("customer_no", ""),
            "业务员": order.get("owner", ""),
            "订单号": order.get("number", ""),
            "物料编码": item.get("material_code", ""),
            "类别": item.get("category", ""),
            "规格型号": requirement,
            "产品型号": item.get("model", ""),
            "电压(V)": voltage or "",
            "频率(Hz)": frequency or "",
            "功率(W)": power or "",
            "订单数量": item.get("quantity", ""),
            "未完工数量": item.get("quantity", ""),
            "接单日期": _date_text(order.get("received_at")),
            "生产单交期": _date_text(order.get("plan_delivery_date") or order.get("delivery_date")),
            "受订日期": _date_text(order.get("received_at")),
            "自制/外购": _supply_kind(item.get("category", ""), item.get("model", "")),
            "备注": "；".join(part for part in notes if part),
        })
        if not voltage or not frequency:
            warnings.append(f"{item.get('model','')} 未从产品要求中识别到电压 / 频率，请手工补")
        if not power:
            warnings.append(f"{item.get('model','')} 未识别到功率，请手工补")
        if not item.get("material_code"):
            warnings.append(f"{item.get('model','')} 缺少物料代码")
        rows.append(row)
    return rows, warnings


DATE_COLUMNS = ("接单日期", "客户交期", "生产单交期", "受订日期", "分析时间", "派工日期",
                "总装生产时间", "包材资料下发日期", "包材采购时间",
                "计划完成日期", "产品交期", "订单下达时间", "交期", "包材预留时间", "月份")
NUMBER_COLUMNS = ("电压(V)", "频率(Hz)", "功率(W)", "订单数量", "未完工数量", "完工数量",
                  "发货数量", "库存数量未发货", "派工数量", "未发货", "剩余数量", "数量")

# 计划总表里可从订单派生的四张表，列名与顺序照抄原表
PARTS_COLUMNS = ["月份", "客户", "业务员/经办人", "订单号", "计划完成日期", "产品大类", "产品要求",
                 "公司型号", "订单数量", "未发货", "包材", "物料代码"]
HOME_COLUMNS = ["计划序号", "月份", "订单号", "物料代码", "产品大类", "规格", "数量", "产品交期",
                "剩余数量", "包材", "备注"]
PACKAGING_COLUMNS = ["订单号", "物料编码", "类别", "规格型号", "要求", "订单下达时间", "交期",
                     "包材预留时间", "备注"]
PLAN_SHEETS = [("最新", PLAN_COLUMNS), ("整体配件汇总", PARTS_COLUMNS),
               ("家用机订单", HOME_COLUMNS), ("包材资料未确定", PACKAGING_COLUMNS)]


def _typed(column, value):
    """把值写成 Excel 认识的原生类型：日期 → date，数量 → 数字。"""
    if value in (None, ""):
        return None
    if column in DATE_COLUMNS:
        try:
            return as_date(value)
        except ValueError:
            return value
    if column in NUMBER_COLUMNS:
        number_value = as_number(value)
        if number_value is None:
            return value
        return int(number_value) if number_value == int(number_value) else float(number_value)
    return value


def _month_text(order):
    try:
        return f"{as_date(order.get('received_at')).month}月"
    except (ValueError, AttributeError):
        return ""


def _plan_date(order):
    return order.get("plan_delivery_date") or order.get("delivery_date") or ""


def parts_rows(order):
    """「整体配件汇总」视图：一行一个型号，月份写成「10月」。"""
    rows = []
    for item in order.get("items", []):
        rows.append({
            "月份": _month_text(order),
            "客户": order.get("customer_no", ""),
            "业务员/经办人": order.get("owner", ""),
            "订单号": order.get("number", ""),
            "计划完成日期": _date_text(_plan_date(order)),
            "产品大类": item.get("category", ""),
            "产品要求": item.get("requirement", ""),
            "公司型号": item.get("model", ""),
            "订单数量": item.get("quantity", ""),
            # 工作台没有发货登记，新导入的单按未发货 = 订单数量
            "未发货": item.get("quantity", ""),
            "包材": item.get("packaging_name", ""),
            "物料代码": item.get("material_code", ""),
        })
    return rows


def home_rows(order):
    """「家用机订单」视图：月份写成接单日期，剩余数量 = 订单数量。"""
    rows = []
    for item in order.get("items", []):
        rows.append({
            "计划序号": order.get("plan_serial", ""),
            "月份": _date_text(order.get("received_at")),
            "订单号": order.get("number", ""),
            "物料代码": item.get("material_code", ""),
            "产品大类": item.get("category", ""),
            "规格": item.get("requirement", ""),
            "数量": item.get("quantity", ""),
            "产品交期": _date_text(_plan_date(order)),
            "剩余数量": item.get("quantity", ""),
            "包材": item.get("packaging_name", ""),
            "备注": order.get("notes", ""),
        })
    return rows


def packaging_rows(order):
    """「包材资料未确定」视图：只列还没确认包材信息的型号。"""
    rows = []
    for item in order.get("items", []):
        if item.get("packaging") or item.get("completed"):
            continue
        reserved = ""
        try:
            delivery = as_date(_plan_date(order))
        except ValueError:
            delivery = None
        if delivery:
            reserved = (delivery - timedelta(days=15)).isoformat()
        rows.append({
            "订单号": order.get("number", ""),
            "物料编码": item.get("material_code", ""),
            "类别": item.get("category", ""),
            "规格型号": item.get("requirement", ""),
            "要求": "",
            "订单下达时间": _date_text(order.get("received_at")),
            "交期": _date_text(_plan_date(order)),
            "包材预留时间": reserved,
            "备注": order.get("notes", ""),
        })
    return rows


def _write_sheet(sheet, columns, rows, head_fill=None):
    """把一批 dict 行写成一张表：表头样式、原生日期/数字、列宽、冻结首行。"""
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    head_fill = head_fill or PatternFill("solid", fgColor="1F3864")
    thin = Side(style="thin", color="D9D9D9")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    sheet.append(columns)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF", size=10)
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border
    sheet.row_dimensions[1].height = 32
    for row in rows:
        sheet.append([_typed(column, row.get(column, "")) for column in columns])
        line = sheet.max_row
        for cell in sheet[line]:
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            cell.border = border
        for column in DATE_COLUMNS:
            if column in columns:
                cell = sheet.cell(row=line, column=columns.index(column) + 1)
                if cell.value is not None:
                    cell.number_format = "yyyy-mm-dd"
        for column in NUMBER_COLUMNS:
            if column in columns:
                sheet.cell(row=line, column=columns.index(column) + 1).alignment = Alignment(
                    horizontal="right", vertical="center")
    wide = {"规格型号": 62, "产品要求": 62, "规格": 62, "备注": 46, "订单号": 18,
            "物料编码": 24, "物料代码": 24, "计划序列号": 14, "计划序号": 14}
    for index, column in enumerate(columns, 1):
        sheet.column_dimensions[get_column_letter(index)].width = wide.get(
            column, max(11, min(22, len(column) * 2 + 4)))
    sheet.freeze_panes = "A2"
    return len(rows)


def export_plan_sheet(path, orders, serials=None, sheet_title="计划总表行"):
    """单 sheet 导出，列与「最新」表一致。"""
    from openpyxl import Workbook

    serials = serials or {}
    book = Workbook()
    sheet = book.active
    sheet.title = sheet_title[:31]
    rows = []
    for order in orders:
        rows.extend(plan_rows(order, serials.get(order["number"], ""))[0])
    total = _write_sheet(sheet, PLAN_COLUMNS, rows)
    book.save(path)
    return total


def export_plan_book(path, orders, serials=None):
    """多 sheet 导出：最新 / 整体配件汇总 / 家用机订单 / 包材资料未确定。"""
    from openpyxl import Workbook

    serials = serials or {}
    book = Workbook()
    book.remove(book.active)
    counts = {}
    for name, columns in PLAN_SHEETS:
        sheet = book.create_sheet(name[:31])
        rows = []
        for order in orders:
            if name == "最新":
                rows.extend(plan_rows(order, serials.get(order["number"], ""))[0])
            elif name == "整体配件汇总":
                rows.extend(parts_rows(order))
            elif name == "家用机订单":
                rows.extend(home_rows(order))
            else:
                rows.extend(packaging_rows(order))
        counts[name] = _write_sheet(sheet, columns, rows)
    book.save(path)
    return counts


def next_serial(existing_serials, today=None):
    """按 X + 年份两位 + 5 位序号 续号；取当年已有最大号 +1。"""
    today = today or date.today()
    prefix = f"X{today:%y}"
    numbers = []
    for value in existing_serials:
        matched = re.fullmatch(r"X(\d{2})(\d{5})", _text(value).upper())
        if matched and f"X{matched.group(1)}" == prefix:
            numbers.append(int(matched.group(2)))
    return f"{prefix}{max(numbers) + 1:05d}" if numbers else f"{prefix}00001"


def read_plan_serials(path, sheet=None):
    """读计划总表的计划序列号（A 列）与订单号（D 列），用于续号和重复检查。"""
    from openpyxl import load_workbook

    book = load_workbook(path, read_only=True, data_only=True)
    try:
        if sheet and sheet in book.sheetnames:
            target = book[sheet]
        else:
            target = book[book.sheetnames[0]]
        serials, numbers = [], []
        for row in target.iter_rows(min_row=2, max_row=3000, max_col=4, values_only=True):
            if not row:
                continue
            if row[0]:
                serials.append(_text(row[0]))
            if len(row) > 3 and row[3]:
                numbers.append(_text(row[3]))
        return serials, numbers
    finally:
        book.close()
