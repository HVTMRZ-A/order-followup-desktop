import csv
from datetime import datetime, date, time
from pathlib import Path
from .domain import new_order, new_item, number, fmt, validate_order

HEADERS = ["订单号", "客户", "经办人", "接单日期", "型号", "产品数量", "要求交期", "合同号", "合同经办人", "销售订单号", "销售经办人", "备注"]
MAPPING = dict(zip(HEADERS, ["number", "customer", "owner", "received_at", "model", "quantity", "delivery_date", "contract_no", "contract_owner", "sales_no", "sales_owner", "notes"]))


def date_value(value, with_time=False):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    else:
        parsed = datetime.fromisoformat(str(value).strip().replace("/", "-"))
    return parsed.isoformat(timespec="seconds") if with_time else parsed.date().isoformat()


def read_import(path, existing_numbers=()):
    path = Path(path)
    if path.suffix.lower() == ".xlsx":
        from openpyxl import load_workbook
        book = load_workbook(path, read_only=True, data_only=True)
        try:
            rows = list(book.active.iter_rows(values_only=True))
        finally:
            book.close()
    elif path.suffix.lower() == ".csv":
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            text = path.read_text(encoding="gb18030")
        rows = list(csv.reader(text.splitlines()))
    else:
        raise ValueError("支持 .xlsx 和 .csv 文件；旧版 .xls 请先另存为 .xlsx")
    if not rows:
        raise ValueError("文件为空")
    if len(rows) > 10001:
        raise ValueError("每次最多导入 10000 行，请拆分文件")
    headers = [str(x or "").strip() for x in rows[0]]
    if len([h for h in headers if h]) != len(set(h for h in headers if h)):
        raise ValueError("表头存在重复列")
    for required in ("订单号", "型号", "产品数量"):
        if required not in headers:
            raise ValueError(f"缺少必填列：{required}，请参考导入模板")
    grouped, errors = {}, []
    existing_numbers = set(existing_numbers)
    for index, row in enumerate(rows[1:], 2):
        if not any(v is not None and str(v).strip() for v in row):
            continue
        data = {MAPPING[h]: v for h, v in zip(headers, row) if h in MAPPING and v is not None and str(v).strip()}
        try:
            no, model = str(data.get("number", "")).strip(), str(data.get("model", "")).strip()
            if not no or not model:
                raise ValueError("订单号和型号不能为空")
            if no in existing_numbers:
                raise ValueError(f"订单 {no} 已存在，请在订单详情中修改")
            quantity = fmt(number(data.get("quantity", ""), "产品数量", positive=True))
            if no not in grouped:
                grouped[no] = new_order()
                grouped[no]["number"] = no
            order = grouped[no]
            for key, value in data.items():
                if key in ("model", "quantity", "number"):
                    continue
                value = date_value(value, key == "received_at") if key in ("received_at", "delivery_date") else str(value).strip()
                if order["items"] and order.get(key) and order[key] != value:
                    raise ValueError(f"订单 {no} 的 {next(h for h,k in MAPPING.items() if k==key)} 与其他行不一致")
                order[key] = value
            if any(i["model"] == model for i in order["items"]):
                raise ValueError(f"订单 {no} 型号 {model} 重复，请先合并数量")
            order["items"].append(new_item(model, quantity))
        except (ValueError, TypeError) as exc:
            errors.append(f"第 {index} 行：{exc}")
    if errors:
        raise ValueError("导入未执行，请修正以下问题：\n" + "\n".join(errors[:25]))
    if not grouped:
        raise ValueError("没有可导入的数据")
    return [validate_order(order) for order in grouped.values()]


def read_any(path, existing_numbers=()):
    """自动识别文件类型：生产作业计划单 → 生产单解析；否则按导入模板解析。"""
    from .production import is_production_sheet, read_production

    if is_production_sheet(path):
        return read_production(path, existing_numbers)
    return read_import(path, existing_numbers)


def write_template(path):
    rows = [HEADERS, ["示例-001", "示例客户", "张三", date.today().isoformat(), "型号A", 100, "", "", "张三", "", "李四", "此行为示例，导入前请替换"],
            ["示例-001", "示例客户", "张三", date.today().isoformat(), "型号B", 50, "", "", "张三", "", "李四", "此行为示例，导入前请替换"]]
    if str(path).lower().endswith(".xlsx"):
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        book = Workbook(); sheet = book.active; sheet.title = "订单导入"
        for row in rows:
            sheet.append(row)
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF"); cell.fill = PatternFill("solid", fgColor="213A5B")
        for col in sheet.columns:
            sheet.column_dimensions[col[0].column_letter].width = 20
        sheet.column_dimensions["L"].width = 44
        sheet.freeze_panes = "A2"
        book.save(path)
    else:
        with open(path, "w", newline="", encoding="utf-8-sig") as stream:
            csv.writer(stream).writerows(rows)
