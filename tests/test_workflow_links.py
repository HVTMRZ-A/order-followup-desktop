import os
from datetime import date
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from openpyxl import Workbook
from workbench.domain import new_order,new_item,demand
from workbench.production import PLAN_COLUMNS,PACKAGING_COLUMNS
from workbench.planbook import read_planbook
from workbench.plan_sync import build_preview,apply_preview,DEFAULT_TARGETS
from workbench.storage import Store
from workbench.ui import MainWindow
from workbench.importer import read_any


def test_workflow_order_to_plan_analysis_daily_and_quantity_change(tmp_path,monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen');monkeypatch.setenv('ORDER_WORKBENCH_DATA',str(tmp_path/'data'))
    a=QApplication.instance() or QApplication([])
    book=Workbook();book.active.title='最新';book.active.append(PLAN_COLUMNS);book.create_sheet('包材资料未确定').append(PACKAGING_COLUMNS)
    source=tmp_path/'plan.xlsx';book.save(source);p,blob=read_planbook(source)
    o=new_order();o['number']='FLOW-1';o['items']=[new_item('A','20')];o['items'][0].update(material_code='M1',category='整机')
    o['materials']=[dict(id='m1',item_id=o['items'][0]['id'],name='纸箱',usage='0.5',arrived='0')]
    s=Store(tmp_path/'db');s.save_order(o);s.save_planbook(p,blob)
    rows=build_preview(p,[o]);p,orders,n=apply_preview(p,[o],DEFAULT_TARGETS,{r['key'] for r in rows});s.save_plan_join(p,orders)
    assert len(p['order_links'])==2
    w=MainWindow(s)
    for reason in ['待确认合同录入','待确认工程 BOM','待确认分析']:
        cell=next(w.todo.item(r,4) for r in range(w.todo.rowCount()) if w.todo.item(r,4).data(Qt.ItemDataRole.UserRole+2) and w.todo.item(r,4).data(Qt.ItemDataRole.UserRole+2)[4]==reason)
        cell.setCheckState(Qt.CheckState.Checked);a.processEvents()
    saved=s.orders()[0];assert saved['contract'] and saved['items'][0]['bom'] and saved['items'][0]['analyzed']
    record=s.daily(date.today().isoformat())['分仓数据'];assert record['order_ids']==[o['id']] and record['state']=='需要跟进'
    assert any(w.todo.item(r,1).text()=='FLOW-1' for r in range(w.todo.rowCount()))
    w.order_management_page.table.setCurrentCell(0,0);w.order_management_page.show_relations();assert '关联未解决跟进 1 项' in w.order_management_page.relations.text()
    w.planbook_page.reload();w.planbook_page.tables[0].setCurrentCell(1,3)
    opened=[];monkeypatch.setattr(w,'edit_order',lambda order=None:opened.append(order))
    w.planbook_page.open_related_order();assert opened[0]['id']==o['id'] and opened[0]['contract']
    saved['items'][0]['quantity']='40';s.save_order(saved)
    rows=build_preview(s.planbook(),[saved]);latest=next(r for r in rows if r['sheet']=='最新');assert latest['state']=='待更新关联行'
    deferred,_,n=apply_preview(s.planbook(),[saved],DEFAULT_TARGETS,set());assert n==0 and deferred['sheets'][0]['cells']['L2']['v']==20
    updated,managed,n=apply_preview(s.planbook(),[saved],DEFAULT_TARGETS,{r['key'] for r in rows});s.save_plan_join(updated,managed)
    assert updated['sheets'][0]['rows']==2 and updated['sheets'][0]['cells']['L2']['v']==40
    assert demand(s.orders()[0],s.orders()[0]['materials'][0])==20
    w.confirm_todo([1,'FLOW-1',date.today().isoformat(),'分仓数据',record['notes'],'','daily:'+date.today().isoformat()])
    assert s.daily(date.today().isoformat())['分仓数据']['state']=='已处理'
    assert s.daily(date.today().isoformat())['分仓数据']['order_ids']==[o['id']]
    s.export_json(tmp_path/'backup.json');s.restore_json(tmp_path/'backup.json')
    assert len(s.planbook()['order_links'])==2
    w.quitting=True;w.close();s.db.close()


def test_production_more_than_200_rows_no_silent_truncation(tmp_path):
    b=Workbook();s=b.active;s.append(['合同编号','LONG-1']);s.append(['公司型号','数量','物料编码','产品要求'])
    for n in range(250):s.append(['M'+str(n),1,'CODE-'+str(n),'说明 '+str(n)])
    p=tmp_path/'production.xlsx';b.save(p);orders=read_any(p)
    assert len(orders[0]['items'])==250
    assert orders[0]['items'][-1]['material_code']=='CODE-249'


def test_xlsx_template_alias_headers_preserve_material_code(tmp_path):
    b=Workbook();s=b.active;s.append(['订单号','公司型号','数量','物料编码','产品要求']);s.append(['T-1','A',5,'001.002','多行\n说明'])
    p=tmp_path/'template.xlsx';b.save(p);o=read_any(p)[0]
    assert o['items'][0]['material_code']=='001.002' and o['items'][0]['requirement']=='多行\n说明'
