"""在 Windows 本机或 GitHub Actions 上打包免安装程序。"""
import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from workbench import VERSION
from workbench.importer import write_template


def main():
    import os
    destination=Path(os.environ.get('WORKBENCH_DIST',str(ROOT/'dist'))).resolve()
    os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase
    from workbench.theme import app_icon
    from PIL import Image
    app=QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR","C:/Windows"))/"Fonts"/"msyhbd.ttc"))
    generated=ROOT/"build";generated.mkdir(exist_ok=True)
    app_icon().pixmap(64,64).save(str(generated/"app.png"))
    Image.open(generated/"app.png").save(generated/"app.ico",sizes=[(16,16),(32,32),(48,48),(64,64)])
    # Conda 可能提供较旧的 VC runtime。让根目录使用 Qt wheel 配套运行库，
    # 避免 Python 先加载旧 DLL 后造成 QtWidgets 导入失败。
    qt=Path(sys.prefix)/"Lib"/"site-packages"/"PySide6"
    runtime_args=[]
    for pattern in ("MSVCP140*.dll","VCRUNTIME140*.dll"):
        for library in qt.glob(pattern):runtime_args.extend(["--add-binary",str(library)+";."])
    subprocess.run([sys.executable,"-c","from PyInstaller.utils.cliutils.makespec import run; run()","--onefile","--windowed","--name","OrderFollowup","--icon",str(generated/"app.ico"),"--collect-data","openpyxl",*runtime_args,str(ROOT/"main.py")],cwd=ROOT,check=True)
    spec=ROOT/"OrderFollowup.spec"
    # Qt 6.12 使用 Windows 自带 ICU。不要把 PATH 中 Poppler/Conda 的
    # 同名 ICU DLL 打入包内，否则其带版本后缀的导出符号不兼容。
    spec.write_text(spec.read_text(encoding="utf-8").replace("pyz = PYZ(a.pure)","a.binaries = [entry for entry in a.binaries if entry[0].lower() not in {'icuuc.dll', 'icuin.dll', 'icudt78.dll'}]\npyz = PYZ(a.pure)"),encoding="utf-8")
    subprocess.run([sys.executable,"-m","PyInstaller","--noconfirm","--clean","--distpath",str(destination),str(spec)],cwd=ROOT,check=True)
    dist=destination;write_template(dist/"订单导入模板.xlsx")
    import shutil
    shutil.copy2(ROOT/"docs"/"使用说明.md",dist/"使用说明.md")
    shutil.copy2(ROOT/"THIRD_PARTY_NOTICES.md",dist/"THIRD_PARTY_NOTICES.md")
    qt=Path(sys.prefix)/"Lib"/"site-packages"/"PySide6"
    license_dir=dist/"licenses";license_dir.mkdir(exist_ok=True)
    for p in qt.rglob("*LGPL*"):
        if p.is_file():shutil.copy2(p,license_dir/p.name)
    for p in (ROOT/"licenses").glob("*"):
        if p.is_file():shutil.copy2(p,license_dir/p.name)
    archive=dist/f"OrderFollowup-v{VERSION}-windows-x64.zip"
    with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as z:
        for name in ["OrderFollowup.exe","订单导入模板.xlsx","使用说明.md","THIRD_PARTY_NOTICES.md"]:z.write(dist/name,name)
        for p in license_dir.glob("*"):z.write(p,"licenses/"+p.name)
    checks=[]
    for p in [dist/"OrderFollowup.exe",archive]:checks.append(hashlib.sha256(p.read_bytes()).hexdigest()+"  "+p.name)
    (dist/"SHA256SUMS.txt").write_text("\n".join(checks)+"\n",encoding="utf-8")
    print("\n".join(checks))


if __name__=="__main__":main()
