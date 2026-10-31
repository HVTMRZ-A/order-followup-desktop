import datetime as dt
from decimal import Decimal

import pytest
from openpyxl import Workbook, load_workbook

from workbench.importer import read_any
from workbench.production import (HOME_COLUMNS, PACKAGING_COLUMNS, PARTS_COLUMNS, PLAN_COLUMNS,
                                  PLAN_SHEETS, as_date, export_plan_book, export_plan_sheet,
                                  extract_ratings, home_rows, is_production_sheet, next_serial,
                                  packaging_rows, parts_rows, plan_rows, read_production)


def make_sheet(path, offset=0, quantity=580, declared=None, extra_rows=0, items=None):
    book = Workbook()
    sheet = book.active
    for _ in range(offset):
        sheet.append([])
    sheet.append(["绿田机械股份有限公司     V1.3"])
    sheet.append([])
    sheet.append(["2026年10月份生产作业计划单"])
    sheet.append(["整机生产单"])
    sheet.append(["", "合同编号：", "26LTJX2043", "", "", "", "", "订单属性：", "新增"])
    sheet.append(["", "客户编号：", "D299", "", "", "", "", "数量：", declared if declared is not None else quantity])
    sheet.append(["计划完成日期:", "", 46356, "", "", "", "", "运输方式：", "1*40HQ"])
    sheet.append([])
    sheet.append(["序号", "产品大类", "客户型号", "公司型号", "数量", "单位", "产品要求", "包材", "BOM状态", "物料代码"])
    rows = items or [
        [1, "太阳能发电机", "", "LE2000-4B", quantity, "台", "壁挂款，230V/50Hz，输出功率2kW，电池容量4019Wh", "绿田",
         "新增", "3.21.00.01.02.10011"],
    ]
    for row in rows:
        sheet.append(row)
    sheet.append(["注意事项：", "", "1.商标按指定设计"])
    sheet.append([])
    sheet.append(["", "复核：", "", "", "", "", "", "经办人：", "戴爽"])
    sheet.append([])
    sheet.append(["", "批准：", "", "", "", "", "", "下单日期：", 46323])
    for _ in range(extra_rows):
        sheet.append([])
    book.save(path)
    return path


def test_parse_real_layout(tmp_path):
    order = read_production(make_sheet(tmp_path / "p.xlsx"))[0]
    assert order["number"] == "26LTJX2043"
    assert order["customer_no"] == "D299"
    assert order["owner"] == "戴爽"
    assert order["transport"] == "1*40HQ"
    assert order["attribute"] == "新增"
    assert order["delivery_date"] == "2026-11-30"
    assert order["received_at"].startswith("2026-10-28")
    assert order["month"] == "2026-10"
    assert order["warnings"] == []
    item = order["items"][0]
    assert item["model"] == "LE2000-4B"
    assert item["quantity"] == "580"
    assert item["material_code"] == "3.21.00.01.02.10011"
    assert item["packaging_name"] == "绿田"
    # 生产单的「包材」是供应商名，不能污染包材确认布尔位
    assert item["packaging"] is False


def test_row_offset_does_not_break(tmp_path):
    order = read_production(make_sheet(tmp_path / "p.xlsx", offset=5))[0]
    assert order["items"][0]["model"] == "LE2000-4B"


def test_quantity_mismatch_warns(tmp_path):
    order = read_production(make_sheet(tmp_path / "p.xlsx", quantity=580, declared=500))[0]
    assert any("不一致" in text for text in order["warnings"])


def test_duplicate_model_merged(tmp_path):
    items = [[1, "太阳能发电机", "", "LE2000-4B", 300, "台", "230V/50Hz", "绿田", "新增", "A1"],
             [2, "太阳能发电机", "", "LE2000-4B", 280, "台", "230V/50Hz", "绿田", "新增", "A1"]]
    order = read_production(make_sheet(tmp_path / "p.xlsx", items=items))[0]
    assert len(order["items"]) == 1
    assert order["items"][0]["quantity"] == "580"
    assert any("合并" in text for text in order["warnings"])


def test_missing_number_rejected(tmp_path):
    book = Workbook()
    sheet = book.active
    sheet.append(["序号", "公司型号", "数量"])
    sheet.append([1, "LE2000-4B", 10])
    path = tmp_path / "bad.xlsx"
    book.save(path)
    with pytest.raises(ValueError, match="合同编号"):
        read_production(path)


def test_existing_number_rejected(tmp_path):
    with pytest.raises(ValueError, match="已存在"):
        read_production(make_sheet(tmp_path / "p.xlsx"), ["26LTJX2043"])


def test_plan_rows_map_to_38_columns(tmp_path):
    order = read_production(make_sheet(tmp_path / "p.xlsx"))[0]
    rows, warnings = plan_rows(order, "X2601352")
    assert list(rows[0]) == PLAN_COLUMNS
    row = rows[0]
    assert row["计划序列号"] == "X2601352"
    assert row["订单号"] == "26LTJX2043"
    assert row["产品型号"] == "LE2000-4B"
    assert row["电压(V)"] == "230"
    assert row["频率(Hz)"] == "50"
    assert row["功率(W)"] == 2000
    assert row["生产单交期"] == "2026-11-30"
    assert row["自制/外购"] == "自制"
    assert warnings == []


def test_ratings_missing_is_flagged(tmp_path):
    items = [[1, "储能逆变器", "", "HL2000-A", 5, "台", "空壳机", "慧勒", "新增", "B1"]]
    order = read_production(make_sheet(tmp_path / "p.xlsx", items=items))[0]
    rows, warnings = plan_rows(order)
    assert rows[0]["电压(V)"] == ""
    assert rows[0]["自制/外购"] == "外购"
    assert any("电压" in text for text in warnings)


def test_extract_ratings():
    assert extract_ratings("230V/50Hz，输出功率2kW") == ("230", "50", 2000)
    assert extract_ratings("220-240V 50/60Hz 6200W") == ("220-240", "50/60", 6200)
    assert extract_ratings("空壳机") == (None, None, None)


def test_export_plan_sheet_matches_plan_header(tmp_path):
    order = read_production(make_sheet(tmp_path / "p.xlsx"))[0]
    target = tmp_path / "plan.xlsx"
    assert export_plan_sheet(target, [order], {"26LTJX2043": "X2601352"}) == 1
    sheet = load_workbook(target).active
    assert [cell.value for cell in sheet[1]] == PLAN_COLUMNS
    values = {column: sheet.cell(row=2, column=index + 1).value for index, column in enumerate(PLAN_COLUMNS)}
    assert values["订单数量"] == 580 and isinstance(values["订单数量"], int)
    assert values["接单日期"] == dt.datetime(2026, 10, 28)
    assert values["生产单交期"] == dt.datetime(2026, 11, 30)
    assert values["计划序列号"] == "X2601352"


def test_derived_views(tmp_path):
    order = read_production(make_sheet(tmp_path / "p.xlsx"))[0]
    order["plan_serial"] = "X2601352"
    parts = parts_rows(order)[0]
    assert list(parts) == PARTS_COLUMNS
    assert parts["月份"] == "10月"
    assert parts["客户"] == "D299"
    assert parts["未发货"] == "580"
    assert parts["包材"] == "绿田"
    home = home_rows(order)[0]
    assert list(home) == HOME_COLUMNS
    assert home["计划序号"] == "X2601352"
    assert home["剩余数量"] == "580"
    pending = packaging_rows(order)
    assert len(pending) == 1 and pending[0]["包材预留时间"] == "2026-11-15"
    order["items"][0]["packaging"] = True
    assert packaging_rows(order) == []


def test_export_plan_book_four_sheets(tmp_path):
    order = read_production(make_sheet(tmp_path / "p.xlsx"))[0]
    target = tmp_path / "book.xlsx"
    counts = export_plan_book(target, [order], {"26LTJX2043": "X2601352"})
    assert list(counts) == [name for name, _ in PLAN_SHEETS]
    book = load_workbook(target)
    assert book.sheetnames == ["最新", "整体配件汇总", "家用机订单", "包材资料未确定"]
    assert [cell.value for cell in book["最新"][1]] == PLAN_COLUMNS
    assert [cell.value for cell in book["整体配件汇总"][1]] == PARTS_COLUMNS
    assert [cell.value for cell in book["家用机订单"][1]] == HOME_COLUMNS
    assert [cell.value for cell in book["包材资料未确定"][1]] == PACKAGING_COLUMNS
    parts = {c: book["整体配件汇总"].cell(2, i + 1).value for i, c in enumerate(PARTS_COLUMNS)}
    assert parts["月份"] == "10月" and parts["客户"] == "D299"
    home = {c: book["家用机订单"].cell(2, i + 1).value for i, c in enumerate(HOME_COLUMNS)}
    assert home["月份"] == dt.datetime(2026, 10, 28)
    assert home["数量"] == 580
    pack = {c: book["包材资料未确定"].cell(2, i + 1).value for i, c in enumerate(PACKAGING_COLUMNS)}
    assert pack["包材预留时间"] == dt.datetime(2026, 11, 15)


def test_date_parsing_variants():
    assert as_date(46356) == dt.date(2026, 11, 30)
    assert as_date(dt.datetime(2026, 1, 5)) == dt.date(2026, 1, 5)
    assert as_date("2026/11/30") == dt.date(2026, 11, 30)
    assert as_date("2026-11-30T00:00:00") == dt.date(2026, 11, 30)
    assert as_date("") is None
    with pytest.raises(ValueError):
        as_date("下个月")


def test_next_serial_keeps_year_prefix():
    assert next_serial(["X2601349", "X2601351"]) == "X2601352"
    assert next_serial(["X2500452", "X2600010"]) == "X2600011"
    assert next_serial([]) == f"X{dt.date.today():%y}00001"


def test_read_any_detects_production_and_template(tmp_path):
    production = make_sheet(tmp_path / "p.xlsx")
    assert is_production_sheet(production)
    assert read_any(production)[0]["number"] == "26LTJX2043"

    book = Workbook()
    sheet = book.active
    sheet.append(["订单号", "型号", "产品数量"])
    sheet.append(["SO-1", "LE2000-4B", 10])
    template = tmp_path / "t.xlsx"
    book.save(template)
    assert not is_production_sheet(template)
    assert read_any(template)[0]["number"] == "SO-1"
