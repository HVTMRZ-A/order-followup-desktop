"""表格格式覆盖：独立于业务数据保存，导出时叠加到原 Excel 样式。"""
import copy
import json
import xml.etree.ElementTree as ET
from .plan_layout import anchor_cell
from openpyxl.utils.cell import get_column_letter, coordinate_to_tuple

NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
TAG=lambda name:'{'+NS+'}'+name
FORMAT_KEYS={'family','size','bold','italic','underline','foreground','background','horizontal','vertical','wrap'}


def selected_cells(table, sheet=None):
    ranges=table.selectedRanges()
    if not ranges and table.currentRow()>=0:
        points=[(table.currentRow()+1,table.currentColumn()+1)]
    else:
        if sum(r.rowCount()*r.columnCount() for r in ranges)>50000:
            raise ValueError('一次最多调整 50000 个单元格，请缩小选区。')
        points=((r+1,c+1) for area in ranges for r in range(area.topRow(),area.bottomRow()+1) for c in range(area.leftColumn(),area.rightColumn()+1))
    return sorted({anchor_cell(sheet,r,c) if sheet else (r,c) for r,c in points})


def effective_style(payload, sheet, address):
    entry=sheet['cells'].get(address,{})
    style_id=entry.get('s',sheet.get('layout',{}).get('cell_styles',{}).get(address,0))
    styles=payload.get('display_styles',[])
    result=copy.deepcopy(styles[style_id] if style_id<len(styles) else {})
    override=sheet.get('format_edits',{}).get(address,{})
    for key,value in override.items():
        if key in ('horizontal','vertical','wrap'):
            result.setdefault('alignment',{})['wrapText' if key=='wrap' else key]=str(int(value)) if key=='wrap' else value
        else:result[key]=value
    return result


def validate_format(changes):
    if set(changes)-FORMAT_KEYS:raise ValueError('不支持的单元格格式。')
    if 'size' in changes and not 6<=float(changes['size'])<=72:raise ValueError('字号请填写 6–72 磅。')
    if 'horizontal' in changes and changes['horizontal'] not in ('left','center','right'):raise ValueError('文字对齐无效。')
    if 'vertical' in changes and changes['vertical'] not in ('top','center','bottom'):raise ValueError('垂直对齐无效。')
    for key in ('foreground','background'):
        if key in changes and changes[key] is not None:
            value=changes[key]
            if not isinstance(value,str) or len(value)!=7 or value[0]!='#':raise ValueError('颜色无效。')
            try:int(value[1:],16)
            except ValueError:raise ValueError('颜色无效。')


def update_formats(sheet, points, changes=None, reset=False):
    if changes:validate_format(changes)
    edits=sheet.setdefault('format_edits',{})
    for r,c in points:
        address=f'{get_column_letter(c)}{r}'
        if reset:edits.pop(address,None)
        else:edits.setdefault(address,{}).update(changes)


class ExportStyles:
    def __init__(self, root):
        self.root=root;self.xfs=root.find(TAG('cellXfs'));self.cache={}

    def style(self, base, changes):
        key=(base,json.dumps(changes,sort_keys=True))
        if key in self.cache:return self.cache[key]
        xf=copy.deepcopy(self.xfs[base])
        fonts=self.root.find(TAG('fonts'))
        font_keys=set(changes)&{'family','size','bold','italic','underline','foreground'}
        if font_keys:
            font=copy.deepcopy(fonts[int(xf.get('fontId','0'))])
            mapping={'family':'name','size':'sz','bold':'b','italic':'i','underline':'u','foreground':'color'}
            for name in font_keys:
                tag=TAG(mapping[name])
                for old in list(font):
                    if old.tag==tag:font.remove(old)
                value=changes[name]
                if name in ('bold','italic','underline'):
                    if value:ET.SubElement(font,tag,**({'val':'single'} if name=='underline' else {}))
                elif name=='foreground':
                    ET.SubElement(font,tag,**({'rgb':'FF'+value[1:].upper()} if value else {'auto':'1'}))
                else:ET.SubElement(font,tag,val=str(value))
                if name=='family':
                    # 主题字体 scheme 会覆盖手选字体。
                    for old in list(font):
                        if old.tag==TAG('scheme'):font.remove(old)
            xf.set('fontId',str(len(fonts)));xf.set('applyFont','1');fonts.append(font);fonts.set('count',str(len(fonts)))
        if 'background' in changes:
            fills=self.root.find(TAG('fills'));fill=ET.Element(TAG('fill'));color=changes['background']
            pattern=ET.SubElement(fill,TAG('patternFill'),patternType='solid' if color else 'none')
            if color:ET.SubElement(pattern,TAG('fgColor'),rgb='FF'+color[1:].upper())
            xf.set('fillId',str(len(fills)));xf.set('applyFill','1');fills.append(fill);fills.set('count',str(len(fills)))
        if set(changes)&{'horizontal','vertical','wrap'}:
            alignment=xf.find(TAG('alignment'))
            if alignment is None:
                alignment=ET.Element(TAG('alignment'));protection=xf.find(TAG('protection'))
                xf.insert(list(xf).index(protection) if protection is not None else len(xf),alignment)
            for name in ('horizontal','vertical','wrap'):
                if name in changes:alignment.set('wrapText' if name=='wrap' else name,str(int(changes[name])) if name=='wrap' else changes[name])
            xf.set('applyAlignment','1')
        index=len(self.xfs);self.xfs.append(xf);self.xfs.set('count',str(len(self.xfs)));self.cache[key]=index
        return index


def export_format(sheet, root, grid, rows, cells, styles):
    for address,changes in sheet.get('format_edits',{}).items():
        r,c=coordinate_to_tuple(address)
        if r not in rows:rows[r]=ET.SubElement(grid,TAG('row'),r=str(r))
        node=cells.get(address)
        if node is None:node=ET.SubElement(rows[r],TAG('c'),r=address);cells[address]=node
        base=int(node.get('s','0'));node.set('s',str(styles.style(base,changes)))
    dimensions=sheet.get('dimension_edits',{})
    for index,pixels in dimensions.get('rows',{}).items():
        r=int(index)
        if r not in rows:rows[r]=ET.SubElement(grid,TAG('row'),r=str(r))
        rows[r].set('ht',str(round(min(409,max(1,pixels*3/4)),3)));rows[r].set('customHeight','1')
    widths=dimensions.get('columns',{})
    if widths:
        cols=root.find(TAG('cols'))
        if cols is None:
            cols=ET.Element(TAG('cols'));root.insert(list(root).index(grid),cols)
        # 原来的跨列定义要拆开，保留每列的隐藏、分级、默认样式等属性。
        definitions={}
        for col in cols:
            for c in range(int(col.get('min')),int(col.get('max'))+1):definitions[c]=dict(col.attrib)
        for index,pixels in widths.items():
            c=int(index);definitions.setdefault(c,{})
            definitions[c].update(width=str(round(min(255,max(.1,(pixels-12)/8)),4)),customWidth='1',bestFit='0')
        cols.clear()
        for c,attrs in sorted(definitions.items()):attrs.update(min=str(c),max=str(c));ET.SubElement(cols,TAG('col'),attrs)
