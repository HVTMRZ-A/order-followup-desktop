import io,os
import xml.etree.ElementTree as ET
from zipfile import ZipFile,ZIP_DEFLATED
import pytest
from openpyxl import Workbook,load_workbook
from openpyxl.drawing.image import Image
from PIL import Image as Raster
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QMessageBox
from workbench.planbook import read_planbook,export_planbook
from workbench.plan_export import ExportScopeDialog

NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main';T=lambda tag:'{'+NS+'}'+tag


def make_source(path):
    book=Workbook();one=book.active;one.title='最新';one.append(['订单号','型号']);one.append(['KEEP','A'])
    two=book.create_sheet('出货计划');two.append(['订单号','型号']);two.append(['BUSINESS-SECRET','B']);book.active=1
    for index,(sheet,color) in enumerate([(one,'red'),(two,'green')]):
        p=path.parent/f'image{index}.png';Raster.new('RGB',(16,16),color).save(p);sheet.add_image(Image(p),'C2')
    book.save(path)
    # openpyxl 默认 inlineStr；构造共享字符串表以验证未选表文本不会被夹带。
    content={};strings=[]
    with ZipFile(path) as original:
        for name in original.namelist():
            data=original.read(name)
            if name.startswith('xl/worksheets/sheet') and name.endswith('.xml'):
                root=ET.fromstring(data)
                for cell in root.iter(T('c')):
                    inline=cell.find(T('is'))
                    if inline is not None:
                        value=''.join(n.text or '' for n in inline.iter(T('t')));cell.remove(inline);cell.set('t','s');ET.SubElement(cell,T('v')).text=str(len(strings));strings.append(value)
                data=ET.tostring(root,encoding='utf-8')
            content[name]=data
    sst=ET.Element(T('sst'),count=str(len(strings)),uniqueCount=str(len(strings)))
    for text in strings:ET.SubElement(ET.SubElement(sst,T('si')),T('t')).text=text
    content['xl/sharedStrings.xml']=ET.tostring(sst,encoding='utf-8')
    rels=ET.fromstring(content['xl/_rels/workbook.xml.rels']);relNS='{http://schemas.openxmlformats.org/package/2006/relationships}'
    ET.SubElement(rels,relNS+'Relationship',Id='rIdStrings',Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings',Target='sharedStrings.xml');content['xl/_rels/workbook.xml.rels']=ET.tostring(rels)
    types=ET.fromstring(content['[Content_Types].xml']);ET.SubElement(types,'{http://schemas.openxmlformats.org/package/2006/content-types}Override',PartName='/xl/sharedStrings.xml',ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml');content['[Content_Types].xml']=ET.tostring(types)
    with ZipFile(path,'w',ZIP_DEFLATED) as out:
        for name,data in content.items():out.writestr(name,data)
    return read_planbook(path)


def test_subset_keeps_only_selected_sheet_text_and_media(tmp_path):
    source=tmp_path/'source.xlsx';p,blob=make_source(source);target=tmp_path/'current.xlsx';export_planbook(target,p,blob,['最新'])
    book=load_workbook(target);assert book.sheetnames==['最新'] and book.active['A2'].value=='KEEP' and len(book.active._images)==1;book.close()
    with ZipFile(target) as archive:
        assert len([n for n in archive.namelist() if n.startswith('xl/media/')])==1
        assert not any(b'BUSINESS-SECRET' in archive.read(n) for n in archive.namelist() if n.endswith('.xml'))
        root=ET.fromstring(archive.read('xl/workbook.xml'));assert root.find(T('bookViews'))[0].get('activeTab')=='0'
    assert source.read_bytes()==blob


def test_all_multiple_and_invalid_names(tmp_path):
    p,blob=make_source(tmp_path/'source.xlsx');target=tmp_path/'all.xlsx';export_planbook(target,p,blob,['最新','出货计划'])
    book=load_workbook(target);assert book.sheetnames==['最新','出货计划'] and book['出货计划']['A2'].value=='BUSINESS-SECRET';book.close()
    for names in ([],['不存在']):
        with pytest.raises(ValueError):export_planbook(tmp_path/'invalid.xlsx',p,blob,names)
    assert not (tmp_path/'invalid.xlsx').exists()


def test_scope_dialog_all_current_and_custom(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen');app=QApplication.instance() or QApplication([])
    names=['最新','出货计划','整体配件汇总'];d=ExportScopeDialog(names,'出货计划');d.confirm();assert d.selected_names==names
    d=ExportScopeDialog(names,'出货计划');d.active.setChecked(True);d.confirm();assert d.selected_names==['出货计划']
    d=ExportScopeDialog(names,'出货计划');d.custom.setChecked(True);d.list.item(0).setCheckState(Qt.CheckState.Checked);d.confirm();assert d.selected_names==['最新','出货计划']
    d=ExportScopeDialog(names,'出货计划');d.custom.setChecked(True)
    for i in range(d.list.count()):d.list.item(i).setCheckState(Qt.CheckState.Unchecked)
    monkeypatch.setattr(QMessageBox,'information',lambda *a,**k:None);d.confirm();assert not d.selected_names and not d.result()


def test_dark_system_palette_keeps_scope_choices_readable(monkeypatch,tmp_path):
    from PySide6.QtGui import QPalette,QColor
    from PySide6.QtWidgets import QStyleOptionButton,QStyle
    from workbench.theme import STYLE
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen');app=QApplication.instance() or QApplication([])
    previous=QPalette(app.palette());previous_style=app.styleSheet();dark=QPalette(previous)
    for group in (QPalette.ColorGroup.Active,QPalette.ColorGroup.Inactive,QPalette.ColorGroup.Disabled):
        dark.setColor(group,QPalette.ColorRole.Base,QColor('#202020'));dark.setColor(group,QPalette.ColorRole.Window,QColor('#202020'));dark.setColor(group,QPalette.ColorRole.Text,QColor('#16202f'));dark.setColor(group,QPalette.ColorRole.Highlight,QColor('#0078d4'))
    app.setPalette(dark);app.setStyleSheet(STYLE)
    try:
        d=ExportScopeDialog(['最新','整体配件汇总','家用机订单','包材交期跟进','包材资料未确定','采购回复配件到料','出货计划'],'整体配件汇总')
        d.show();app.processEvents()
        assert '全部 7' in d.summary.text()
        # 非自选模式下，禁用列表仍应是浅色、文字可读。
        snapshot=d.list.viewport().grab().toImage()
        assert snapshot.pixelColor(snapshot.width()-12,snapshot.height()-12).lightness()>225
        d.custom.setChecked(True);d.list.setCurrentRow(2);d.list.item(2).setCheckState(Qt.CheckState.Checked);app.processEvents()
        assert '2 / 7' in d.summary.text()
        screenshot=d.list.viewport().grab().toImage()
        unselected=d.list.visualItemRect(d.list.item(0));selected=d.list.visualItemRect(d.list.item(2))
        plain=screenshot.pixelColor(unselected.right()-12,unselected.center().y());highlight=screenshot.pixelColor(selected.right()-12,selected.center().y())
        assert plain.lightness()>240 and highlight.lightness()>210 and plain!=highlight
        # 单选按钮的实心中心明确区分选中与未选中，避免每个选项看起来都选了。
        for radio,checked in ((d.custom,True),(d.all,False)):
            option=QStyleOptionButton();option.initFrom(radio)
            indicator=radio.style().subElementRect(QStyle.SubElement.SE_RadioButtonIndicator,option,radio)
            color=radio.grab().toImage().pixelColor(indicator.center())
            assert color.blue()>color.red()+80 if checked else color.lightness()>240
        d.grab().save(str(tmp_path/'dark-system-scope.png'))
        d.close()
    finally:app.setPalette(previous);app.setStyleSheet(previous_style)
