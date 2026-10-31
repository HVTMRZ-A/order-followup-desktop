from copy import deepcopy
import pytest
from openpyxl import Workbook,load_workbook
from workbench.domain import new_order,new_item
from workbench.production import PLAN_COLUMNS,PACKAGING_COLUMNS
from workbench.planbook import read_planbook,export_planbook
from workbench.plan_sync import build_preview,apply_preview,DEFAULT_TARGETS
from workbench.storage import Store


def setup(tmp_path):
    b=Workbook();s=b.active;s.title='最新';s.append(PLAN_COLUMNS)
    b.create_sheet('包材资料未确定').append(PACKAGING_COLUMNS)
    b.create_sheet('出货计划').append(['发柜数量','订单号','业务员','型号','数量','毛重kg','总毛重kg','备注'])
    path=tmp_path/'plan.xlsx';b.save(path);payload,source=read_planbook(path)
    o=new_order();o['number']='S001';o['items']=[new_item('A','10')];o['items'][0].update(material_code='M001',category='储能电源')
    return payload,source,o


def test_preview_is_readonly_confirm_export_and_retry(tmp_path):
    p,source,o=setup(tmp_path);before=deepcopy(p);rows=build_preview(p,[o]);assert p==before
    assert len(rows)==2 and all(r['state']=='新增' for r in rows)
    saved,orders,count=apply_preview(p,[o],DEFAULT_TARGETS,{r['key'] for r in rows})
    assert count==2 and not orders[0]['plan_pending'] and p==before
    assert all(r['state']=='已存在' for r in build_preview(saved,orders))
    again,orders,count=apply_preview(saved,orders,DEFAULT_TARGETS,{r['key'] for r in rows});assert count==0
    path=tmp_path/'out.xlsx';export_planbook(path,again,source)
    b=load_workbook(path,read_only=True);assert b['最新'].max_row==2
    assert b['最新']['D2'].value=='S001';assert b['最新']['L2'].value==10
    from datetime import datetime
    assert isinstance(b['最新']['Q2'].value,datetime);b.close()


def test_unchecked_rows_defer_and_missing_plan_is_actionable(tmp_path):
    p,source,o=setup(tmp_path)
    saved,orders,count=apply_preview(p,[o],DEFAULT_TARGETS,set())
    assert count==0 and saved==p and len(orders[0]['plan_pending'])==2
    assert all('尚未确认' in t['reason'] for t in orders[0]['plan_pending'])
    saved,orders,count=apply_preview(None,[o],DEFAULT_TARGETS,set())
    assert saved is None and count==0 and all('先导入' in t['reason'] for t in orders[0]['plan_pending'])


def test_conflict_does_not_overwrite(tmp_path):
    p,source,o=setup(tmp_path);rows=build_preview(p,[o]);p,_,_=apply_preview(p,[o],DEFAULT_TARGETS,{r['key'] for r in rows})
    o['items'][0]['quantity']='20';preview=build_preview(p,[o]);assert preview[0]['state']=='待更新关联行'
    p,orders,n=apply_preview(p,[o],DEFAULT_TARGETS,set())
    assert n==0 and p['sheets'][0]['cells']['L2']['v']==10
    assert any('尚未确认' in t['reason'] for t in orders[0]['plan_pending'])


def test_incomplete_shipping_to_todo_then_resolve(tmp_path):
    p,source,o=setup(tmp_path);row=build_preview(p,[o],['出货计划'])[0];assert row['state']=='暂不能加入'
    p,orders,n=apply_preview(p,[o],['出货计划'],set());assert orders[0]['plan_pending']
    orders[0]['plan_overrides']={row['key']:{'发柜数量':'第1柜','数量':'2','毛重kg':'3.25'}}
    row=build_preview(p,orders,['出货计划'])[0];assert row['state']=='新增' and row['values']['总毛重kg']==6.5
    p,orders,n=apply_preview(p,orders,['出货计划'],{row['key']});assert n==1 and not orders[0]['plan_pending']


def test_missing_code_adds_row_but_keeps_followup(tmp_path):
    p,source,o=setup(tmp_path);o['items'][0]['material_code']='';rows=build_preview(p,[o])
    p,orders,n=apply_preview(p,[o],DEFAULT_TARGETS,{r['key'] for r in rows});assert n==2
    assert any('物料编码' in t['reason'] for t in orders[0]['plan_pending'])


def test_fill_existing_blanks_requires_confirmation_and_resolves(tmp_path):
    p,source,o=setup(tmp_path);o['items'][0]['material_code']='';rows=build_preview(p,[o])
    p,orders,n=apply_preview(p,[o],DEFAULT_TARGETS,{r['key'] for r in rows})
    orders[0]['items'][0]['material_code']='M001';rows=build_preview(p,orders)
    assert rows[0]['state']=='补充空白'
    untouched,deferred,n=apply_preview(p,orders,DEFAULT_TARGETS,set());assert n==0
    assert untouched['sheets'][0]['cells'].get('E2',{}).get('v') in ('',None)
    filled,done,n=apply_preview(p,orders,DEFAULT_TARGETS,{r['key'] for r in rows})
    assert n==2 and filled['sheets'][0]['cells']['E2']['v']=='M001'
    assert not done[0]['plan_pending'] and filled['sheets'][0]['rows']==2


def test_reimport_plan_requires_reconfirmation(tmp_path):
    p,source,o=setup(tmp_path);s=Store(tmp_path/'db');s.save_order(o);s.save_planbook(p,source)
    rows=build_preview(p,[o]);joined,orders,n=apply_preview(p,[o],DEFAULT_TARGETS,{r['key'] for r in rows});s.save_plan_join(joined,orders)
    s.save_planbook(p,source);assert not s.orders()[0]['plan_sync_checked'];s.db.close()


def test_plan_and_order_followups_save_atomically_and_restore(tmp_path):
    p,source,o=setup(tmp_path);s=Store(tmp_path/'db');s.save_order(o);s.save_planbook(p,source)
    rows=build_preview(p,[o]);joined,orders,n=apply_preview(p,[o],DEFAULT_TARGETS,{r['key'] for r in rows});s.save_plan_join(joined,orders)
    assert s.orders()[0]['plan_sync_checked'] and s.planbook()['sheets'][0]['rows']==2
    backup=tmp_path/'backup.json';s.export_json(backup);s.restore_json(backup)
    assert s.orders()[0]['plan_sync_checked'] and s.planbook()['sheets'][0]['rows']==2
    bad=deepcopy(orders);bad[0]['number']=''
    with pytest.raises(ValueError):s.save_plan_join(p,bad)
    assert s.planbook()['sheets'][0]['rows']==2;s.db.close()


def test_ui_cancel_does_not_join_or_clear_pending(tmp_path,monkeypatch):
    from PySide6.QtWidgets import QApplication
    from workbench.ui import MainWindow
    from workbench.plan_join_ui import PlanJoinDialog
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen');monkeypatch.setenv('ORDER_WORKBENCH_DATA',str(tmp_path/'ui'))
    a=QApplication.instance() or QApplication([]);p,source,o=setup(tmp_path);s=Store(tmp_path/'db');s.save_order(o);s.save_planbook(p,source)
    w=MainWindow(s);d=PlanJoinDialog(s,[o],w);d.reject()
    assert s.planbook()['sheets'][0]['rows']==1 and not s.orders()[0]['plan_sync_checked']
    assert any('待确认加入' in w.todo.item(r,4).text() for r in range(w.todo.rowCount()))
    d=PlanJoinDialog(s,[o],w);d.accept();w.refresh();assert d.count==2 and s.orders()[0]['plan_sync_checked']
    assert not any('待确认加入' in w.todo.item(r,4).text() for r in range(w.todo.rowCount()))
    w.quitting=True;w.close();s.db.close()
