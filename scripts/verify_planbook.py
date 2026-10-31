"""只读原件，在独立目录核对全表导入、另存和界面。"""
import os,sys,json,hashlib
from pathlib import Path
from zipfile import ZipFile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
out=ROOT/'outputs'/'planbook-verification';out.mkdir(parents=True,exist_ok=True)
os.environ['ORDER_WORKBENCH_DATA']=str(out/'data')
from workbench.planbook import read_planbook,export_planbook,edit_cell,EXPECTED_SHEETS
from workbench.importer import read_any
from workbench.storage import Store
source=Path(sys.argv[1]);production=Path(sys.argv[2]);before=hashlib.sha256(source.read_bytes()).hexdigest()
payload,blob=read_planbook(source);assert [s['name'] for s in payload['sheets']]==EXPECTED_SHEETS
target=out/'planbook-roundtrip.xlsx';export_planbook(target,payload,blob);restored,_=read_planbook(target)
assert [(s['name'],s['cells']) for s in restored['sheets']]==[(s['name'],s['cells']) for s in payload['sheets']]
import copy
edited=copy.deepcopy(payload);address='A'+str(edited['sheets'][0]['rows']+1)
edit_cell(edited['sheets'][0],address,'本地导出验证（测试副本）')
changed_target=out/'planbook-edited-roundtrip.xlsx';export_planbook(changed_target,edited,blob)
edited_read,_=read_planbook(changed_target)
assert edited_read['sheets'][0]['cells'][address]['v']=='本地导出验证（测试副本）'
for old,new in zip(payload['sheets'],edited_read['sheets']):
    for coord,cell in old['cells'].items():assert new['cells'][coord]==cell
with ZipFile(source) as a,ZipFile(target) as b:
    parts=[n for n in a.namelist() if n.startswith(('xl/media/','xl/charts/','xl/drawings/'))]
    assert all(a.read(n)==b.read(n) for n in parts)
assert hashlib.sha256(source.read_bytes()).hexdigest()==before
orders=read_any(production);store=Store();store.save_planbook(payload,blob)
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from workbench.ui import MainWindow,STYLE
a=QApplication([])
for name in ['msyh.ttc','msyhbd.ttc']:QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+name)
a.setStyleSheet(STYLE);w=MainWindow(store);w.nav.setCurrentRow(4);w.show();a.processEvents();w.grab().save(str(out/'planbook.png'))
result={'visible_sheets':[{'name':s['name'],'rows':s['rows'],'cols':s['cols'],'cells':len(s['cells'])} for s in payload['sheets']],
        'visible_values_formulas_preserved':True,'media_chart_drawing_parts_preserved':len(parts),'source_unchanged':True,
        'edited_export_preserves_existing_cells':True,
        'production_orders':len(orders),'production_items':sum(len(o['items']) for o in orders)}
(out/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=True));w.quitting=True;w.close();store.db.close()
