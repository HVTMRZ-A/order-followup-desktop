# 第三方组件说明

- Qt / PySide6 Essentials / Shiboken6：The Qt Company，LGPL v3 / GPL v3 或商业许可。此应用使用动态库。用户可依 LGPL 对这些组件调试、替换或重新链接；完整应用源代码和构建命令公开提供，未禁止为调试库修改进行逆向工程。
  - 源码与对应版本：https://code.qt.io/cgit/pyside/pyside-setup.git/ 和 https://download.qt.io/archive/qt/
  - LGPL v3：https://www.gnu.org/licenses/lgpl-3.0.html
- openpyxl：MIT，https://openpyxl.readthedocs.io/
- Python：Python Software Foundation License，https://docs.python.org/3/license.html
- PyInstaller：GPL 2.0 带分发例外，https://pyinstaller.org/en/stable/license.html

发布包附 LGPL 文本。需要替换 Qt 库时，可从本仓库使用调整后的依赖重新构建整个 EXE。
