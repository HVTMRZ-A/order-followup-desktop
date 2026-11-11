"""计划表显示元数据；不改写原表的值、公式或合并范围。"""
import io
import colorsys
import posixpath
import xml.etree.ElementTree as ET
from functools import lru_cache
from zipfile import ZipFile
from openpyxl.utils.cell import range_boundaries, coordinate_to_tuple, get_column_letter
from openpyxl.styles.colors import COLOR_INDEX

NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
TAG = lambda name: '{' + NS + '}' + name


def color_value(node, theme, indexed):
    """Excel 静态颜色：RGB、主题色（含明暗调整）、索引色。"""
    if node is None or node.get('auto') in ('1', 'true'):
        return None
    value = node.get('rgb')
    if value is None and node.get('theme') is not None:
        value = theme.get(int(node.get('theme')))
    if value is None and node.get('indexed') is not None:
        index = int(node.get('indexed'))
        value = indexed[index] if 0 <= index < min(64, len(indexed)) else None
    if not value:
        return None
    value = value[-6:]
    try:
        rgb = tuple(int(value[i:i+2], 16)/255 for i in (0, 2, 4))
        tint = max(-1, min(1, float(node.get('tint', '0'))))
        if tint:
            hue, light, saturation = colorsys.rgb_to_hls(*rgb)
            light = light*(1+tint) if tint < 0 else light*(1-tint)+tint
            rgb = colorsys.hls_to_rgb(hue, light, saturation)
        return '#' + ''.join(f'{round(c*255):02x}' for c in rgb)
    except (ValueError, TypeError):
        return None


def layout_ready(payload):
    return 'display_styles' in payload and payload.get('display_style_version') == 3 and all(s.get('layout', {}).get('version') == 1 for s in payload['sheets'])


def read_layout(source):
    with ZipFile(io.BytesIO(source)) as book:
        root = ET.fromstring(book.read('xl/styles.xml'))
        theme = {}
        if 'xl/theme/theme1.xml' in book.namelist():
            drawing = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
            scheme = ET.fromstring(book.read('xl/theme/theme1.xml')).find('.//' + drawing + 'clrScheme')
            names = ('lt1', 'dk1', 'lt2', 'dk2', 'accent1', 'accent2', 'accent3', 'accent4', 'accent5', 'accent6', 'hlink', 'folHlink')
            for index, name in enumerate(names):
                color = scheme.find(drawing + name) if scheme is not None else None
                if color is not None and len(color):
                    theme[index] = color[0].get('lastClr') or color[0].get('val')
        palette = root.find(TAG('colors') + '/' + TAG('indexedColors'))
        indexed = [c.get('rgb') for c in palette] if palette is not None else COLOR_INDEX
        fonts = root.find(TAG('fonts'))
        fills = root.find(TAG('fills'))
        styles = []
        for xf in root.find(TAG('cellXfs')):
            font = fonts[int(xf.get('fontId', '0'))]
            alignment = xf.find(TAG('alignment'))
            size = font.find(TAG('sz'))
            name = font.find(TAG('name'));underline = font.find(TAG('u'))
            pattern = fills[int(xf.get('fillId', '0'))].find(TAG('patternFill'))
            background = color_value(pattern.find(TAG('fgColor')), theme, indexed) if pattern is not None and pattern.get('patternType') == 'solid' else None
            styles.append(dict(bold=font.find(TAG('b')) is not None and font.find(TAG('b')).get('val', '1') != '0',
                               italic=font.find(TAG('i')) is not None and font.find(TAG('i')).get('val', '1') != '0',
                               size=float(size.get('val', '10')) if size is not None else 10,
                               family=name.get('val') if name is not None else '',
                               underline=underline is not None and underline.get('val','single')!='none',
                               alignment=dict(alignment.attrib) if alignment is not None else {},
                               foreground=color_value(font.find(TAG('color')), theme, indexed), background=background))
        wb = ET.fromstring(book.read('xl/workbook.xml'))
        rels = {r.get('Id'): r.get('Target') for r in ET.fromstring(book.read('xl/_rels/workbook.xml.rels'))}
        layouts = {}
        for spec in wb.find(TAG('sheets')):
            if spec.get('state', 'visible') != 'visible':
                continue
            member = rels[spec.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')]
            member = member.lstrip('/') if member.startswith('/') else posixpath.normpath('xl/' + member)
            layout = dict(version=1, merges=[], columns=[], heights={}, default_height=24, cell_styles={})
            with book.open(member) as stream:
                for _, node in ET.iterparse(stream, events=('end',)):
                    if node.tag == TAG('mergeCell'):
                        layout['merges'].append(node.get('ref'))
                    elif node.tag == TAG('col') and node.get('width'):
                        layout['columns'].append(dict(first=int(node.get('min')), last=int(node.get('max')), width=float(node.get('width'))))
                    elif node.tag == TAG('sheetFormatPr'):
                        layout['default_height'] = float(node.get('defaultRowHeight', '24'))
                    elif node.tag == TAG('row') and node.get('ht'):
                        layout['heights'][node.get('r')] = float(node.get('ht'))
                    elif node.tag == TAG('c') and node.get('s'):
                        style_id = int(node.get('s')); address = node.get('r')
                        if address and style_id < len(styles) and (styles[style_id]['background'] or styles[style_id]['foreground']):
                            row, col = coordinate_to_tuple(address)
                            if row <= 50000 and col <= 300:layout['cell_styles'][address] = style_id
                    node.clear()
            layouts[spec.get('name')] = layout
    return styles, layouts


def ensure_layout(payload, source):
    """旧版已导入记录从留存原件补齐显示格式，保留所有后续修改。"""
    if layout_ready(payload):
        return False
    styles, layouts = read_layout(source)
    payload['display_styles'] = styles
    payload['display_style_version'] = 3
    for sheet in payload['sheets']:
        sheet['layout'] = layouts.get(sheet['name'], dict(version=1, merges=[], columns=[], heights={}))
        for ref in sheet['layout']['merges']:
            left, top, right, bottom = range_boundaries(ref)
            if 1 <= left <= right <= 300 and 1 <= top <= bottom <= 50000:
                sheet['cols'] = max(sheet['cols'], right)
                sheet['rows'] = max(sheet['rows'], bottom)
    return True


def merge_ranges(sheet):
    return _merge_ranges(tuple(sheet.get('layout', {}).get('merges', [])), sheet['rows'], sheet['cols'])


@lru_cache(maxsize=32)
def _merge_ranges(refs, rows, cols):
    result = []
    for ref in refs:
        try:
            left, top, right, bottom = range_boundaries(ref)
            if 1 <= left <= right <= cols and 1 <= top <= bottom <= rows:
                result.append((left, top, right, bottom))
        except (ValueError, TypeError):
            continue
    return tuple(result)


def anchor_cell(sheet, row, column):
    for left, top, right, bottom in merge_ranges(sheet):
        if left <= column <= right and top <= row <= bottom:
            return top, left
    return row, column


def effective_value(sheet, row, column):
    row, column = anchor_cell(sheet, row, column)
    return sheet['cells'].get(f'{get_column_letter(column)}{row}', {}).get('v')


def cell_entry(sheet, address):
    row, column = coordinate_to_tuple(address)
    row, column = anchor_cell(sheet, row, column)
    return sheet['cells'].get(f'{get_column_letter(column)}{row}', {})


def order_groups(sheet):
    from .plan_sync import headers
    columns, header = headers(sheet)
    number_column = columns.get('订单号')
    if not number_column:
        return [], columns, header
    ranges = merge_ranges(sheet)
    def value(row, column):
        for left, top, right, bottom in ranges:
            if left <= column <= right and top <= row <= bottom:
                row, column = top, left
                break
        return sheet['cells'].get(f'{get_column_letter(column)}{row}', {}).get('v')
    groups = []
    for row in range(header + 1, sheet['rows'] + 1):
        number = value(row, number_column)
        if number in ('', None):
            continue
        number = str(number)
        if groups and groups[-1]['number'] == number and groups[-1]['end'] == row - 1:
            groups[-1]['end'] = row
        else:
            groups.append(dict(start=row, end=row, number=number))
    for group in groups:
        group['context'] = ' '.join(str(value(group['start'], column) or '') for column in range(1, number_column+1))
    return groups, columns, header
