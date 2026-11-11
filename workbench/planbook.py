"""完整计划总表：按实际非空单元格读取，避免原表夸大的整表维度。"""
import copy
import io
import posixpath
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from openpyxl.styles.numbers import BUILTIN_FORMATS, is_date_format
from openpyxl.utils.cell import coordinate_to_tuple, get_column_letter
from openpyxl.utils.datetime import from_excel, to_excel, WINDOWS_EPOCH, MAC_EPOCH

NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
TAG = lambda name: '{'+NS+'}'+name
EXPECTED_SHEETS = ['最新', '整体配件汇总', '家用机订单',
                   '包材交期跟进', '包材资料未确定', '采购回复配件到料', '出货计划']


def is_planbook(path):
    if Path(path).suffix.lower() not in ('.xlsx','.xlsm'):return False
    with ZipFile(path) as book:
        root=ET.fromstring(book.read('xl/workbook.xml'))
        names=[s.get('name') for s in root.find(TAG('sheets')) if s.get('state','visible')=='visible']
    if len(set(names)&set(EXPECTED_SHEETS))>=2:return True
    if names==['最新']:
        from openpyxl import load_workbook
        b=load_workbook(path,read_only=True,data_only=True)
        try:
            for row in b.active.iter_rows(max_row=3,max_col=40,values_only=True):
                fields={''.join(str(v or '').split()) for v in row}
                if {'订单号','计划序列号','产品型号'}<=fields:return True
        finally:b.close()
    return False


def read_planbook(path):
    source = Path(path).read_bytes()
    with ZipFile(io.BytesIO(source)) as book:
        strings = []
        if 'xl/sharedStrings.xml' in book.namelist():
            root = ET.fromstring(book.read('xl/sharedStrings.xml'))
            strings = [''.join(t.text or '' for t in si.iter(TAG('t'))) for si in root]
        workbook = ET.fromstring(book.read('xl/workbook.xml'))
        links = {r.attrib['Id']: r.attrib['Target'] for r in ET.fromstring(book.read('xl/_rels/workbook.xml.rels'))}
        props = workbook.find(TAG('workbookPr'))
        epoch = MAC_EPOCH if props is not None and props.get('date1904') in ('1','true') else WINDOWS_EPOCH
        styles = ET.fromstring(book.read('xl/styles.xml'))
        formats = dict(BUILTIN_FORMATS)
        fmts = styles.find(TAG('numFmts'))
        if fmts is not None:
            formats.update({int(f.get('numFmtId')):f.get('formatCode') for f in fmts})
        xfs = styles.find(TAG('cellXfs'))
        dates = {i for i,x in enumerate(xfs if xfs is not None else []) if is_date_format(formats.get(int(x.get('numFmtId','0')), 'General'))}
        sheets = []
        for spec in workbook.find(TAG('sheets')):
            if spec.get('state','visible') != 'visible':continue
            target = links[spec.get('{'+REL+'}id')]
            member = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
            cells = {}; maxrow = maxcol = 1
            with book.open(member) as stream:
                for event, node in ET.iterparse(stream, events=('end',)):
                    if node.tag == TAG('c'):
                        v, f, inline = node.find(TAG('v')), node.find(TAG('f')), node.find(TAG('is'))
                        if v is not None or f is not None or inline is not None:
                            address = node.get('r'); raw = v.text if v is not None else None; kind = node.get('t','n')
                            value = raw
                            if kind == 's' and raw is not None: value = strings[int(raw)]
                            elif kind == 'inlineStr': value = ''.join(t.text or '' for t in inline.iter(TAG('t'))) if inline is not None else ''
                            elif kind == 'b': value = raw == '1'
                            elif kind == 'n' and raw is not None:
                                try: value = float(raw); value = int(value) if value.is_integer() else value
                                except ValueError: pass
                            style = int(node.get('s','0')); isdate = style in dates and isinstance(value,(int,float))
                            if isdate:
                                try: value = from_excel(value,epoch).isoformat()
                                except (ValueError,OverflowError): isdate = False
                            entry = {'v':value,'s':style,'date':isdate}
                            if f is not None:
                                entry['f'] = '='+f.text if f.text else ''; entry['formula_attrs'] = dict(f.attrib)
                            cells[address] = entry
                            row,col = coordinate_to_tuple(address); maxrow=max(maxrow,row); maxcol=max(maxcol,col)
                        node.clear()
                    elif node.tag == TAG('row'):
                        node.clear()
            if maxrow > 50000 or maxcol > 300:
                raise ValueError(f"{spec.get('name')} 的实际数据超出支持范围（50000 行、300 列）")
            sheets.append(dict(name=spec.get('name'),state=spec.get('state','visible'),member=member,
                               rows=maxrow,cols=maxcol,cells=cells,edits={},formulas_stale=False))
    payload = dict(name=Path(path).name,source_path=str(Path(path).resolve()),sheets=sheets,epoch1904=epoch==MAC_EPOCH)
    from .plan_layout import ensure_layout
    ensure_layout(payload, source)
    return payload, source


def displayed(sheet, address):
    entry=sheet['cells'].get(address,{})
    if entry.get('f') and sheet.get('formulas_stale'):
        return entry['f'] or '共享公式（导出后由 Excel 计算）'
    v=entry.get('v')
    if v is None:return entry.get('f') or ''
    if entry.get('date'):return str(v).replace('T00:00:00','')
    return str(v)


def edit_cell(sheet,address,value):
    from .plan_layout import anchor_cell
    row,col=coordinate_to_tuple(address);row,col=anchor_cell(sheet,row,col);address=f'{get_column_letter(col)}{row}'
    entry=copy.deepcopy(sheet['cells'].get(address,{'s':sheet.get('layout',{}).get('cell_styles',{}).get(address,0)}))
    if 'f' in entry:raise ValueError('原表公式格仅查看，请修改它所引用的输入格；导出后由 Excel 重算。')
    entry.pop('f',None);entry.pop('formula_attrs',None)
    entry['v']=value
    # 在日期单元格中继续接受 ISO 日期；其它内容保持原样。
    if entry.get('date'):
        try:datetime.fromisoformat(str(value))
        except ValueError:entry['date']=False
    sheet['cells'][address]=entry;sheet['edits'][address]=entry
    r,c=coordinate_to_tuple(address);sheet['rows']=max(sheet['rows'],r);sheet['cols']=max(sheet['cols'],c)
    # 跨表公式也可能依赖此格，由调用者标记全工作簿过期。


def export_planbook(path,payload,source,sheet_names=None):
    if payload.get('source_path') and Path(path).resolve()==Path(payload['source_path']).resolve():
        raise ValueError('请另存为新文件，不能覆盖导入的原计划总表。')
    target=io.BytesIO()
    names=[s['name'] for s in payload['sheets']]
    selected=set(names if sheet_names is None else sheet_names)
    if not selected or not selected<=set(names):raise ValueError('请选择至少一张有效的工作表。')
    subset=selected!=set(names)
    with ZipFile(io.BytesIO(source)) as original, ZipFile(target,'w',ZIP_DEFLATED) as result:
        wb=ET.fromstring(original.read('xl/workbook.xml'));relations=ET.fromstring(original.read('xl/_rels/workbook.xml.rels'))
        relation_map={r.get('Id'):r for r in relations};excluded=set();removed_ids=set()
        sheetlist=wb.find(TAG('sheets'))
        index_map={};visible_index=0
        for old_index,spec in enumerate(sheetlist):
            if spec.get('state','visible')=='visible' and spec.get('name') in selected:index_map[old_index]=visible_index;visible_index+=1
        for spec in list(sheetlist):
            if spec.get('state','visible') != 'visible' or spec.get('name') not in selected:
                rid=spec.get('{'+REL+'}id');removed_ids.add(rid);link=relation_map[rid];member=link.get('Target')
                excluded.add(member.lstrip('/') if member.startswith('/') else posixpath.normpath('xl/'+member));sheetlist.remove(spec);relations.remove(link)
        names=wb.find(TAG('definedNames'))
        if names is not None:
            for name in list(names):
                if name.get('localSheetId') is not None:
                    old=int(name.get('localSheetId'))
                    if old not in index_map:names.remove(name)
                    else:name.set('localSheetId',str(index_map[old]))
        for view in wb.findall(TAG('bookViews')+'/'+TAG('workbookView')):
            for attribute in ('activeTab','firstSheet'):
                if view.get(attribute) is not None:view.set(attribute,str(index_map.get(int(view.get(attribute)),0)))
        for rel in list(relations):
            if rel.get('Type','').endswith('/calcChain'):relations.remove(rel)
        changed={s['member']:s for s in payload['sheets'] if s['name'] in selected and (s.get('edits') or s.get('format_edits') or s.get('dimension_edits'))}
        styles_original=original.read('xl/styles.xml');styles_root=ET.fromstring(styles_original);xfs=styles_root.find(TAG('cellXfs'));date_styles={}
        for sheet in changed.values():
            for entry in sheet['edits'].values():
                if entry.get('date') and entry.get('s',0) not in date_styles:
                    base=entry.get('s',0);xf=copy.deepcopy(xfs[base]);xf.set('numFmtId','14');xf.set('applyNumberFormat','1')
                    date_styles[base]=len(xfs);xfs.append(xf)
        if date_styles:xfs.set('count',str(len(xfs)))
        from .cell_format import ExportStyles,export_format
        formatter=ExportStyles(styles_root)
        # ZIP 条目可能先出现 styles.xml；先生成全部样式，再写任何条目。
        rendered={}
        for member,sheet in changed.items():
                data=original.read(member);root=ET.fromstring(data);grid=root.find(TAG('sheetData'))
                rows={int(row.get('r')):row for row in grid};cells={c.get('r'):c for row in grid for c in row}
                for address,entry in sheet['edits'].items():
                    r,c=coordinate_to_tuple(address)
                    if r not in rows:
                        rows[r]=ET.Element(TAG('row'),r=str(r));grid.append(rows[r])
                    node=cells.get(address)
                    if node is None:node=ET.SubElement(rows[r],TAG('c'),r=address,s=str(entry.get('s',0)));cells[address]=node
                    for child in list(node):
                        if child.tag in (TAG('f'),TAG('v'),TAG('is')):node.remove(child)
                    value=entry.get('v');node.attrib.pop('t',None)
                    if value is None or value=='':continue
                    if entry.get('date'):
                        node.set('s',str(date_styles[entry.get('s',0)]))
                        value=to_excel(datetime.fromisoformat(str(value)),MAC_EPOCH if payload.get('epoch1904') else WINDOWS_EPOCH)
                    if isinstance(value,bool):node.set('t','b');ET.SubElement(node,TAG('v')).text='1' if value else '0'
                    elif isinstance(value,(int,float)):ET.SubElement(node,TAG('v')).text=str(value)
                    else:
                        node.set('t','inlineStr');text=ET.SubElement(ET.SubElement(node,TAG('is')),TAG('t'));text.set('{http://www.w3.org/XML/1998/namespace}space','preserve');text.text=str(value)
                export_format(sheet,root,grid,rows,cells,formatter)
                grid[:]=sorted(grid,key=lambda row:int(row.get('r')))
                for row in grid:row[:]=sorted(row,key=lambda cell:coordinate_to_tuple(cell.get('r'))[1])
                dim=root.find(TAG('dimension'))
                if dim is not None:dim.set('ref',f"A1:{get_column_letter(sheet['cols'])}{sheet['rows']}")
                rendered[member]=xml_bytes(root,data)
        keep=None
        if subset:
            from .plan_export import retained_parts,compact_strings,compact_properties
            keep=retained_parts(original,relations)
            compact_strings(original,[s['member'] for s in payload['sheets'] if s['name'] in selected],rendered,xml_bytes)
            compact_properties(original,[s['name'] for s in payload['sheets'] if s['name'] in selected],rendered,xml_bytes)
        for info in original.infolist():
            if info.filename in excluded or info.filename=='xl/calcChain.xml':continue
            if keep is not None and info.filename not in keep:continue
            data=original.read(info.filename)
            if info.filename in rendered:data=rendered[info.filename]
            elif info.filename=='xl/styles.xml' and (date_styles or formatter.cache):
                data=xml_bytes(styles_root,styles_original)
            elif info.filename=='xl/workbook.xml':
                calc=wb.find(TAG('calcPr'))
                if calc is None:calc=ET.SubElement(wb,TAG('calcPr'))
                calc.set('fullCalcOnLoad','1');calc.set('forceFullCalc','1');data=xml_bytes(wb,data)
            elif info.filename=='xl/_rels/workbook.xml.rels':
                for rel in list(relations):
                    if rel.get('Type','').endswith('/calcChain'):relations.remove(rel)
                data=xml_bytes(relations,data)
            elif info.filename=='[Content_Types].xml':
                root=ET.fromstring(data)
                for node in list(root):
                    part=node.get('PartName','').lstrip('/')
                    if part in excluded | {'xl/calcChain.xml'} or part and keep is not None and part not in keep:root.remove(node)
                data=xml_bytes(root,data)
            # 未修改的 XML、图表、图片、外部链接等逐项保留。
            result.writestr(info,data)
    Path(path).write_bytes(target.getvalue())


def xml_bytes(root,original):
    declarations=re.findall(rb'xmlns(?::([\w]+))?="([^"]+)"',original[:8000])
    for prefix,uri in declarations:
        try:ET.register_namespace(prefix.decode(),uri.decode())
        except ValueError:pass
    data=ET.tostring(root,encoding='utf-8',xml_declaration=True)
    missing=[]
    for prefix,uri in declarations:
        name=b'xmlns'+(b':'+prefix if prefix else b'')
        if name+b'=' not in data:missing.append(b' '+name+b'="'+uri+b'"')
    if missing:data=re.sub(rb'(<[A-Za-z_][^\s/>]*)',lambda m:m.group(1)+b''.join(missing),data,count=1)
    return data
