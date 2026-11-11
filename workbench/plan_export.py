"""工作表范围选择及所选工作簿的资源清理。"""
import copy
import posixpath
import xml.etree.ElementTree as ET
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette,QColor
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QLabel,QRadioButton,QListWidget,QListWidgetItem,QDialogButtonBox,QMessageBox)

NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
TAG=lambda name:'{'+NS+'}'+name


class ExportScopeDialog(QDialog):
    def __init__(self,names,current,parent=None):
        super().__init__(parent);self.setWindowTitle('选择导出范围');self.resize(520,560);self.names=list(names);self.current=current;self.selected_names=[]
        from .theme import export_scope_stylesheet
        self.setObjectName('exportScopeDialog');self.setStyleSheet(export_scope_stylesheet())
        palette=QPalette(self.palette())
        for group in (QPalette.ColorGroup.Active,QPalette.ColorGroup.Inactive,QPalette.ColorGroup.Disabled):
            for role,color in ((QPalette.ColorRole.Base,'#ffffff'),(QPalette.ColorRole.Window,'#f4f7fc'),(QPalette.ColorRole.Text,'#16202f'),(QPalette.ColorRole.WindowText,'#16202f'),(QPalette.ColorRole.Highlight,'#e7efff'),(QPalette.ColorRole.HighlightedText,'#16202f')):
                palette.setColor(group,role,QColor(color))
        self.setPalette(palette)
        box=QVBoxLayout(self);box.addWidget(QLabel('选择要导出的工作表，原文件不会被覆盖。'))
        self.all=QRadioButton(f'全部工作表（{len(names)} 张）');self.all.setChecked(True)
        self.active=QRadioButton('当前工作表：'+current);self.custom=QRadioButton('勾选工作表')
        for control in (self.all,self.active,self.custom):box.addWidget(control)
        self.list=QListWidget();self.list.setObjectName('exportSheetList');self.list.setPalette(palette)
        for name in names:
            item=QListWidgetItem(name);item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable);item.setCheckState(Qt.CheckState.Checked if name==current else Qt.CheckState.Unchecked);self.list.addItem(item)
        self.list.setEnabled(False);self.custom.toggled.connect(self.list.setEnabled);box.addWidget(self.list,1)
        self.summary=QLabel();self.summary.setObjectName('exportSelectionSummary');self.summary.setWordWrap(True);box.addWidget(self.summary)
        hint=QLabel('勾选工作表时，以方框内的勾为准；浅蓝色只表示当前点中的一行。');hint.setObjectName('exportSelectionHint');hint.setWordWrap(True);box.addWidget(hint)
        for control in (self.all,self.active,self.custom):control.toggled.connect(self.update_summary)
        self.list.itemChanged.connect(self.update_summary);self.update_summary()
        note=QLabel('只导出选中的工作表。若公式引用未选中的表，导出后可能无法计算；可改选“全部工作表”。');note.setWordWrap(True);box.addWidget(note)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('下一步');buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消');buttons.accepted.connect(self.confirm);buttons.rejected.connect(self.reject);box.addWidget(buttons)
    def update_summary(self,*args):
        if self.all.isChecked():self.summary.setText(f'将导出全部 {len(self.names)} 张工作表')
        elif self.active.isChecked():self.summary.setText('将导出当前工作表：'+self.current)
        else:
            count=sum(self.list.item(i).checkState()==Qt.CheckState.Checked for i in range(self.list.count()))
            self.summary.setText(f'已勾选 {count} / {len(self.names)} 张工作表')
    def confirm(self):
        self.selected_names=self.names[:] if self.all.isChecked() else [self.current] if self.active.isChecked() else [self.list.item(i).text() for i in range(self.list.count()) if self.list.item(i).checkState()==Qt.CheckState.Checked]
        if not self.selected_names:QMessageBox.information(self,'尚未选择','至少勾选一张工作表。');return
        self.accept()


def retained_parts(book, workbook_rels):
    """只保留从已选工作表/工作簿可达的资源，去掉未选表的附件。"""
    available=set(book.namelist());keep={'[Content_Types].xml'};pending=['']
    seen=set()
    while pending:
        owner=pending.pop()
        if owner in seen:continue
        seen.add(owner)
        if owner:keep.add(owner)
        relations=posixpath.join(posixpath.dirname(owner),'_rels',posixpath.basename(owner)+'.rels') if owner else '_rels/.rels'
        if relations not in available:continue
        keep.add(relations)
        root=workbook_rels if relations=='xl/_rels/workbook.xml.rels' else ET.fromstring(book.read(relations))
        for relation in root:
            if relation.get('TargetMode')=='External':continue
            target=relation.get('Target','').split('#',1)[0]
            member=target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join(posixpath.dirname(owner),target))
            if member in available:pending.append(member)
    return keep


def compact_strings(book,members,rendered,xml_bytes):
    part='xl/sharedStrings.xml'
    if part not in book.namelist():return
    sheets={member:ET.fromstring(rendered.get(member,book.read(member))) for member in members}
    used=set();references=0
    for root in sheets.values():
        for cell in root.iter(TAG('c')):
            if cell.get('t')=='s':
                value=cell.find(TAG('v'))
                if value is not None and value.text is not None:used.add(int(value.text));references+=1
    original=book.read(part);strings=ET.fromstring(original);entries=strings.findall(TAG('si'))
    mapping={old:new for new,old in enumerate(sorted(used))}
    for entry in entries:strings.remove(entry)
    for index,old in enumerate(sorted(used)):strings.insert(index,copy.deepcopy(entries[old]))
    strings.set('count',str(references));strings.set('uniqueCount',str(len(used)));rendered[part]=xml_bytes(strings,original)
    for member,root in sheets.items():
        for cell in root.iter(TAG('c')):
            if cell.get('t')=='s':
                value=cell.find(TAG('v'))
                if value is not None and value.text is not None:value.text=str(mapping[int(value.text)])
        rendered[member]=xml_bytes(root,rendered.get(member,book.read(member)))


def compact_properties(book,names,rendered,xml_bytes):
    part='docProps/app.xml'
    if part not in book.namelist():return
    original=book.read(part);root=ET.fromstring(original)
    props='{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}'
    vt='{http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes}'
    for tag in ('HeadingPairs','TitlesOfParts'):
        old=root.find(props+tag)
        if old is not None:root.remove(old)
    head=ET.SubElement(root,props+'HeadingPairs');pairs=ET.SubElement(head,vt+'vector',size='2',baseType='variant')
    ET.SubElement(ET.SubElement(pairs,vt+'variant'),vt+'lpstr').text='Worksheets'
    ET.SubElement(ET.SubElement(pairs,vt+'variant'),vt+'i4').text=str(len(names))
    titles=ET.SubElement(root,props+'TitlesOfParts');vector=ET.SubElement(titles,vt+'vector',size=str(len(names)),baseType='lpstr')
    for name in names:ET.SubElement(vector,vt+'lpstr').text=name
    rendered[part]=xml_bytes(root,original)
