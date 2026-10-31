"""独立测试目录内验证实际 EXE 替换、旧程序保留与订单数据保留。"""
import hashlib
import json
import os
import shutil
import sys
import time
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
DATA=ROOT/"outputs"/"upgrade-data"
INSTALL=ROOT/"outputs"/"upgrade-install"
os.environ["ORDER_WORKBENCH_DATA"]=str(DATA)
from workbench.domain import new_order,new_item
from workbench.storage import Store
from workbench.updater import launch_replacement


def main():
    INSTALL.mkdir(parents=True,exist_ok=True)
    source=ROOT/"dist"/"OrderFollowup.exe"
    target=INSTALL/"OrderFollowup.exe"
    old_exe=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else source
    shutil.copy2(old_exe,target)
    # 仅给测试副本添加尾部标记，确保前后哈希不同。
    with target.open("ab") as stream:stream.write(b"\nprevious-build-test-marker\n")
    old_hash=hashlib.sha256(target.read_bytes()).hexdigest()
    store=Store();order=new_order();order["number"]="UPGRADE-VERIFY";order["items"]=[new_item("升级保留验证型号","123")]
    if not store.orders():store.save_order(order)
    store.save_daily("2026-10-31",{"分仓数据":{"state":"需要跟进","notes":"升级后必须保留"}})
    before_orders=store.orders();before_daily=store.daily_all();backup=store.backup();store.db.close()
    log=DATA/"updates"/"update-result.txt";log.unlink(missing_ok=True)
    report=DATA/"self-test.json";report.unlink(missing_ok=True)
    process=subprocess.Popen([str(target),"--verify-update",str(source)])
    process.wait(timeout=45)
    for _ in range(100):
        if log.exists() and report.exists():break
        time.sleep(0.2)
    assert log.exists(),"未生成更新结果"
    assert "更新完成" in log.read_text(encoding="utf-8-sig"),log.read_text(encoding="utf-8-sig")
    assert report.exists(),"更新后 EXE 未完成重新启动自检"
    assert json.loads(report.read_text(encoding="utf-8"))["stored_orders"]==len(before_orders)
    assert hashlib.sha256(target.read_bytes()).hexdigest()==hashlib.sha256(source.read_bytes()).hexdigest()
    assert hashlib.sha256(target.with_name("OrderFollowup.previous.exe").read_bytes()).hexdigest()==old_hash
    store=Store();assert store.orders()==before_orders
    # 正常打开/关闭界面会刷新保存时间，并补齐当日三个栏目；业务内容必须保持。
    for day, records in before_daily:
        restored=store.daily(day)
        for name, record in records.items():
            for key in ("state","notes"):
                assert restored[name].get(key)==record.get(key)
    store.db.close()
    result=dict(replacement="passed",previous_exe="preserved",orders="preserved",daily="preserved",backup=str(backup))
    (ROOT/"outputs"/"upgrade-check.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=True))


if __name__=="__main__":main()
