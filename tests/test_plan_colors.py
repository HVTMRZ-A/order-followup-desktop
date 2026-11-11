import copy
import xml.etree.ElementTree as ET
from openpyxl import Workbook,load_workbook
from openpyxl.styles import Font,PatternFill,Color
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication,QWidget
from workbench.planbook import read_planbook,edit_cell,export_planbook
from workbench.plan_layout import ensure_layout,color_value
from workbench.plan_ui import PlanBookWidget
from workbench.storage import Store
from workbench.theme import STYLE


def color_book(path):
    book=Workbook();s=book.active;s.title='最新';s.append(['订单号','型号','备注'])
    s.append(['C1','A','原颜色']);s.append(['C2','B','普通白底'])
    s['A1'].fill=PatternFill('solid',fgColor='123456');s['A1'].font=Font(color='FFFFFF')
    s['C2'].fill=PatternFill('solid',fgColor=Color(theme=4,tint=.5))
    s['C2'].font=Font(color=Color(indexed=10))
    s['B3'].font=Font(color=Color(theme=1))
    s['C3'].fill=PatternFill('solid',fgColor=Color(indexed=13))
    s['B2'].fill=PatternFill('solid',fgColor='00FF00')
    s['B4'].fill=PatternFill('solid',fgColor='FFFF00');s['A4']='留空颜色'
    book.save(path);return read_planbook(path)


def test_rgb_theme_tint_indexed_blank_and_upgrade_preserve_edits(tmp_path):
    p,blob=color_book(tmp_path/'colors.xlsx');s=p['sheets'][0];styles=p['display_styles']
    assert styles[s['cells']['A1']['s']]['background']=='#123456'
    assert styles[s['cells']['A1']['s']]['foreground']=='#ffffff'
    assert styles[s['cells']['C2']['s']]['background']=='#a7c0de'
    assert styles[s['cells']['C2']['s']]['foreground']=='#ff0000'
    assert styles[s['cells']['B3']['s']]['foreground']=='#000000'
    assert styles[s['cells']['C3']['s']]['background']=='#ffff00'
    blank_style=s['layout']['cell_styles']['B4'];assert 'B4' not in s['cells']
    edit_cell(s,'B4','新内容');assert s['cells']['B4']['s']==blank_style
    edit_cell(s,'C2','保留编辑');edits=copy.deepcopy(s['edits']);p.pop('display_style_version')
    assert ensure_layout(p,blob) and p['sheets'][0]['edits']==edits
    target=tmp_path/'out.xlsx';export_planbook(target,p,blob);out=load_workbook(target)
    assert out.active['B4'].fill.fgColor.rgb=='00FFFF00' and out.active['B4'].value=='新内容'
    assert out.active['C2'].fill.fgColor.type=='theme' and out.active['C2'].value=='保留编辑'
    out.close()


def test_color_switch_uses_original_roles_and_persists(tmp_path,monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen');app=QApplication.instance() or QApplication([])
    app.setStyleSheet(STYLE)
    p,blob=color_book(tmp_path/'colors.xlsx');store=Store(tmp_path/'db');store.save_planbook(p,blob)
    parent=QWidget();parent.resize(1100,800);w=PlanBookWidget(store,parent);w.resize(1100,800);parent.show();app.processEvents();t=w.tables[0]
    assert not t.alternatingRowColors()
    assert t.item(0,0).background().color()==QColor('#123456') and t.item(0,0).foreground().color()==QColor('#ffffff')
    assert t.item(3,1).background().color()==QColor('#ffff00')
    # 检查实际绘制，不仅是数据角色；避开文字和网格边线。
    rect=t.visualItemRect(t.item(0,0));pixel=t.viewport().grab().toImage().pixelColor(rect.left()+4,rect.top()+4)
    assert pixel==QColor('#123456')
    w.show_colors.setChecked(False);assert w.tables[0].item(0,0).background().style().value==0
    assert store.get('plan_show_colors')=='0'
    w.show_colors.setChecked(True);assert w.tables[0].item(0,0).background().color()==QColor('#123456')
    parent.close();store.db.close()


def test_auto_system_and_tint_bounds():
    assert color_value(ET.Element('color',auto='1'),{},[]) is None
    assert color_value(ET.Element('color',indexed='64'),{},['FF0000']*66) is None
    assert color_value(ET.Element('color',rgb='112233',tint='1'),{},[])=='#ffffff'
    assert color_value(ET.Element('color',rgb='112233',tint='-1'),{},[])=='#000000'
