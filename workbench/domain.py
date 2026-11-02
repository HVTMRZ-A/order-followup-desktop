"""业务规则；时间均为本机本地时间，提醒使用自然日。"""
from datetime import datetime, date, time, timedelta
from decimal import Decimal, InvalidOperation
from uuid import uuid4


def stamp():
    return datetime.now().isoformat(timespec="seconds")


def uid():
    return uuid4().hex


def number(value, label="数量", positive=False):
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f"{label}必须是有效数字")
    if not result.is_finite() or result < 0 or (positive and result <= 0):
        raise ValueError(f"{label}必须{'大于' if positive else '大于等于'}零")
    if result > Decimal("1000000000000"):
        raise ValueError(f"{label}超出允许范围")
    return result


def fmt(value):
    return format(Decimal(str(value)).normalize(), "f")


def new_item(model="", quantity="1"):
    return dict(id=uid(), model=model, quantity=quantity, bom=False, analyzed=False,
                analysis_at="", packaging=False, completed=False)


def new_order():
    return dict(id=uid(), number="", customer="", owner="", received_at=stamp(),
                delivery_date="", contract_no="", contract_owner="", contract=False,
                sales_no="", sales_owner="", notes="", items=[], materials=[], updated_at=stamp())


def validate_order(order):
    if not str(order.get("number", "")).strip():
        raise ValueError("请填写订单号")
    datetime.fromisoformat(order["received_at"])
    for key in ('delivery_date', 'plan_delivery_date'):
        if order.get(key):
            date.fromisoformat(order[key])
    if not order.get("items"):
        raise ValueError("请至少添加一个型号")
    ids, models = set(), set()
    for item in order["items"]:
        if not item.get("model", "").strip():
            raise ValueError("型号不能为空")
        if item["id"] in ids or item["model"] in models:
            raise ValueError("同一订单的型号不能重复，请合并数量")
        ids.add(item["id"])
        models.add(item["model"])
        number(item["quantity"], "产品数量", positive=True)
        if item.get("analyzed") and not item.get("analysis_at"):
            raise ValueError("已确认分析的型号需要填写分析日期")
        if item.get("analysis_at"):
            date.fromisoformat(item["analysis_at"])
    material_ids = set()
    for material in order.get("materials", []):
        if material["id"] in material_ids:
            raise ValueError("包材记录重复")
        material_ids.add(material["id"])
        if material.get("item_id") not in ids:
            raise ValueError("包材关联的型号不存在，请先调整包材关联")
        if not material.get("name", "").strip():
            raise ValueError("包材名称不能为空")
        number(material["usage"], "单件包材用量", positive=True)
        number(material.get("arrived", "0"), "已到数量")
        for key in ("due_date", "remind_date", "arrival_date", "request_date"):
            if material.get(key):
                date.fromisoformat(material[key])
    return order


def demand(order, material):
    item = next(i for i in order["items"] if i["id"] == material["item_id"])
    return number(item["quantity"], positive=True) * number(material["usage"], positive=True)


def all_checked(order, key):
    return bool(order["items"]) and all(i.get(key, False) for i in order["items"])


def progress(order, key):
    return f"{sum(bool(i.get(key)) for i in order['items'])}/{len(order['items'])}"


def confirm_all(order, key, checked, analysis_date=None):
    for item in order["items"]:
        item[key] = checked
        if key == "analyzed":
            item["analysis_at"] = (item.get("analysis_at") or analysis_date or date.today().isoformat()) if checked else ""


def reminders(order, now=None):
    now = now or datetime.now()
    if all_checked(order, "completed"):
        return []
    result = []
    if not order.get("contract") and now >= datetime.fromisoformat(order["received_at"]) + timedelta(days=1):
        result.append(dict(level=2, reason="合同超过 1 天未确认", model="整单", kind="contract"))
    for item in order["items"]:
        if item.get("completed"):
            continue
        if item.get("analyzed") and item.get("analysis_at") and not item.get("packaging"):
            due = datetime.combine(date.fromisoformat(item["analysis_at"]) + timedelta(days=10), time.min)
            if now >= due:
                result.append(dict(level=2, reason="分析满 10 天，包材信息未确认", model=item["model"], kind="packaging"))
    active = {i["id"] for i in order["items"] if not i.get("completed")}
    for material in order.get("materials", []):
        if material["item_id"] not in active or number(material.get("arrived", "0")) >= demand(order, material):
            continue
        due = material.get("remind_date") or material.get("due_date")
        if due and now >= datetime.combine(date.fromisoformat(due), time(9)):
            late = bool(material.get("due_date") and date.fromisoformat(material["due_date"]) < now.date())
            model = next(i["model"] for i in order["items"] if i["id"] == material["item_id"])
            result.append(dict(level=3 if late else 2, reason=f"{material['name']}：{'交期已过，尚未到齐' if late else '包材到料跟进'}", model=model, kind="delivery"))
    return result

