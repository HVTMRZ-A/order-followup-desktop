from datetime import datetime
from decimal import Decimal
import copy
import csv
import json
import pytest
from workbench.domain import new_order, new_item, reminders, confirm_all, all_checked, demand, validate_order, number
from workbench.storage import Store
from workbench.importer import read_import, HEADERS, write_template
from workbench.updater import version_tuple, asset_info


def order():
    o=new_order();o.update(number="SO-001",received_at="2026-10-01T10:30:00")
    o["items"]=[new_item("A","120"),new_item("B","50")]
    return o


def test_contract_exact_24_hours():
    o=order()
    assert not reminders(o,datetime(2026,10,2,10,29,59))
    assert reminders(o,datetime(2026,10,2,10,30))[0]["kind"]=="contract"
    o["contract"]=True
    assert not reminders(o,datetime(2026,10,2,10,30))


def test_packaging_day_ten_and_model_override():
    o=order();o["contract"]=True
    confirm_all(o,"analyzed",True,"2026-10-01")
    assert not reminders(o,datetime(2026,10,10,23,59))
    assert len(reminders(o,datetime(2026,10,11)))==2
    o["items"][0]["packaging"]=True
    assert len(reminders(o,datetime(2026,10,11)))==1
    confirm_all(o,"packaging",True)
    assert not reminders(o,datetime(2026,10,11))


def test_bulk_does_not_confirm_later_added_model():
    o=order();confirm_all(o,"bom",True);assert all_checked(o,"bom")
    o["items"].append(new_item("C"));assert not all_checked(o,"bom")
    confirm_all(o,"analyzed",True,"2026-10-01");confirm_all(o,"analyzed",False)
    assert all(not i["analysis_at"] for i in o["items"])


def material(o):
    return dict(id="m1",item_id=o["items"][0]["id"],name="纸箱",usage="0.125",arrived="0",due_date="2026-10-20",remind_date="2026-10-18")


def test_decimal_demand_and_9am_boundary():
    o=order();o["contract"]=True;m=material(o);o["materials"]=[m]
    assert demand(o,m)==Decimal("15")
    assert not reminders(o,datetime(2026,10,18,8,59,59))
    assert reminders(o,datetime(2026,10,18,9))[0]["level"]==2
    assert reminders(o,datetime(2026,10,21,9))[0]["level"]==3
    m["arrived"]="14.9";assert reminders(o,datetime(2026,10,21,9))
    m["arrived"]="15";assert not reminders(o,datetime(2026,10,21,9))


def test_due_date_fallback_and_completion_suppresses():
    o=order();o["contract"]=True;m=material(o);m["remind_date"]="";o["materials"]=[m]
    assert not reminders(o,datetime(2026,10,20,8,59))
    assert reminders(o,datetime(2026,10,20,9))
    o["items"][0]["completed"]=True
    assert not reminders(o,datetime(2026,10,20,9))
    confirm_all(o,"completed",True);o["contract"]=False
    assert not reminders(o,datetime(2026,10,20,9))


@pytest.mark.parametrize("bad",["-1","NaN","Infinity","abc",""])
def test_invalid_numbers(bad):
    with pytest.raises(ValueError):number(bad)


def test_invalid_model_link():
    o=order();m=material(o);m["item_id"]="missing";o["materials"]=[m]
    with pytest.raises(ValueError):validate_order(o)


def test_backup_restore_reopen(tmp_path):
    path=tmp_path/"orders.sqlite3";s=Store(path);o=order();o["materials"]=[material(o)];s.save_order(o)
    s.save_daily("2026-10-01",{"分仓数据":{"state":"需要跟进","notes":"SO-001 待核实"}})
    backup=tmp_path/"backup.json";s.export_json(backup)
    o["notes"]="修改后";s.save_order(o);s.restore_json(backup);s.db.close()
    reopened=Store(path);assert reopened.orders()[0]["notes"]==""
    assert reopened.orders()[0]["materials"][0]["usage"]=="0.125"
    assert reopened.daily("2026-10-01")["分仓数据"]["state"]=="需要跟进"
    assert reopened.history(o["id"])


def test_atomic_duplicate_import(tmp_path):
    s=Store(tmp_path/"db");o=order();s.save_order(o);another=order();another["number"]="SO-002";duplicate=order()
    with pytest.raises(Exception):s.save_orders([another,duplicate])
    assert len(s.orders())==1


def test_import_group_and_reject_duplicate(tmp_path):
    p=tmp_path/"orders.csv"
    with p.open("w",encoding="utf-8-sig",newline="") as f:
        csv.writer(f).writerows([HEADERS,["SO1","客户","经办","2026-10-01","A",100],["SO1","客户","经办","2026-10-01","B",25]])
    orders=read_import(p);assert len(orders)==1;assert len(orders[0]["items"])==2
    with pytest.raises(ValueError,match="已存在"):read_import(p,["SO1"])


def test_import_conflicting_owner(tmp_path):
    p=tmp_path/"bad.csv";p.write_text("订单号,型号,产品数量,经办人\nS,A,1,甲\nS,B,2,乙",encoding="utf-8")
    with pytest.raises(ValueError,match="不一致"):read_import(p)


def test_xlsx_template_roundtrip(tmp_path):
    p=tmp_path/"template.xlsx";write_template(p);orders=read_import(p)
    assert len(orders)==1;assert len(orders[0]["items"])==2


def test_restore_invalid_backup_does_not_replace(tmp_path):
    s=Store(tmp_path/"db");o=order();s.save_order(o)
    p=tmp_path/"bad.json";p.write_text(json.dumps({"format":"order-followup-backup-v1","orders":[{}],"daily":[]}),encoding="utf-8")
    with pytest.raises(ValueError):s.restore_json(p)
    assert s.orders()[0]["number"]=="SO-001"


def test_update_semver_and_source():
    assert version_tuple("v0.10.0")>version_tuple("0.9.9")
    with pytest.raises(ValueError):version_tuple("1.0.0-beta")
    with pytest.raises(ValueError):asset_info({"assets":[dict(name="OrderFollowup.exe",browser_download_url="https://example.com/app.exe",digest="sha256:"+"a"*64)]})


def test_update_rejects_missing_checksum():
    with pytest.raises(ValueError,match="SHA-256"):asset_info({"assets":[dict(name="OrderFollowup.exe",browser_download_url="https://github.com/HVTMRZ-A/order-followup-desktop/releases/download/v1.0.0/OrderFollowup.exe")]})


def test_update_download_validates_content(tmp_path,monkeypatch):
    import io,hashlib
    import workbench.updater as u
    content=b"test executable bytes";url="https://github.com/HVTMRZ-A/order-followup-desktop/releases/download/v1.0.0/OrderFollowup.exe"
    release={"tag_name":"v1.0.0","assets":[dict(name="OrderFollowup.exe",browser_download_url=url,digest="sha256:"+hashlib.sha256(content).hexdigest(),size=len(content))]}
    monkeypatch.setattr(u,"data_dir",lambda:tmp_path);monkeypatch.setattr(u.urllib.request,"urlopen",lambda *a,**k:io.BytesIO(content))
    target=u.download_release(release);assert target.read_bytes()==content
    monkeypatch.setattr(u.urllib.request,"urlopen",lambda *a,**k:io.BytesIO(b"tampered".ljust(len(content),b"X")))
    with pytest.raises(ValueError,match="校验失败"):u.download_release(release)
    assert target.read_bytes()==content
