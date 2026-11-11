import os
import sys
import traceback
from pathlib import Path


def main():
    from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon
    from PySide6.QtCore import QLockFile
    from workbench.storage import data_dir
    from workbench.ui import MainWindow, STYLE
    app=QApplication(sys.argv);app.setApplicationName("OrderFollowupDesktop");app.setStyle("Fusion");app.setStyleSheet(STYLE)
    if '--diagnose-update' in sys.argv:
        if not os.environ.get('ORDER_WORKBENCH_DATA'):
            raise RuntimeError('Update diagnosis requires an isolated ORDER_WORKBENCH_DATA directory')
        import json
        from workbench import VERSION, updater
        release = updater.get_release()
        path = updater.download_release(release)
        result = dict(version=VERSION, downloaded=release['tag_name'], bytes=path.stat().st_size,
                      path=str(path), verified=True)
        (data_dir()/'download-self-test.json').write_text(json.dumps(result), encoding='utf-8')
        return 0
    if "--self-test" in sys.argv:
        if not os.environ.get("ORDER_WORKBENCH_DATA"):
            raise RuntimeError("Self-test requires an isolated ORDER_WORKBENCH_DATA directory")
        import json
        import ssl
        from workbench.storage import Store
        from workbench.importer import read_any, write_template
        from workbench.production import PLAN_COLUMNS, is_production_sheet, plan_rows
        from workbench import VERSION
        store=Store();template=data_dir()/"self-test.xlsx";write_template(template)
        parsed=read_any(template);window=MainWindow(store);window.show();app.processEvents()
        from workbench.plan_export import ExportScopeDialog
        scope=ExportScopeDialog(['测试工作表'],'测试工作表',window);scope.confirm()
        window.grab().save(str(data_dir()/"self-test.png"))
        report=dict(version=VERSION,pages=window.pages.count(),import_orders=len(parsed),import_models=len(parsed[0]["items"]),ssl=ssl.OPENSSL_VERSION,stored_orders=len(store.orders()),
                    production_detected=is_production_sheet(template),plan_columns=len(plan_rows(parsed[0])[0][0]) if plan_rows(parsed[0])[0] else 0,
                    plan_columns_expected=len(PLAN_COLUMNS),orders_columns=window.orders_table.columnCount(),
                    drag_ready=bool(window.acceptDrops() and window.drop_overlay is not None),
                    todo_grouping=hasattr(window,"toggle_todo_group"),order_views=window.order_tabs.count(),
                    order_editing=hasattr(window.order_management_page,"edit_selected_item"),
                    order_deletion=hasattr(window.order_management_page,"delete_selected_order"),
                    recycle_bin=hasattr(store,"restore_deleted"),
                    undo_redo=hasattr(window,"edit_history") and hasattr(window,"undo_action") and hasattr(window,"redo_action"),
                    original_colors=hasattr(window.planbook_page,"show_colors"),
                    cell_formatting=all(hasattr(page,'format_bar') for page in (window.planbook_page,window.order_management_page)) and hasattr(window,'material_format_bar'),
                    plan_save=hasattr(window.planbook_page,'save_current'),plan_removal=hasattr(window.planbook_page,'remove_selected_records'),
                    export_scope=scope.selected_names==['测试工作表'],
                    usability_controls=hasattr(window,'todo_process') and hasattr(window,'material_search') and hasattr(window.planbook_page,'cell_value') and hasattr(window.planbook_page,'format_toggle'))
        (data_dir()/"self-test.json").write_text(json.dumps(report,ensure_ascii=False),encoding="utf-8")
        window.quitting=True;window.close();window.tray.hide();store.db.close();return 0
    if "--verify-update" in sys.argv:
        if not os.environ.get("ORDER_WORKBENCH_DATA") or not getattr(sys,"frozen",False):
            raise RuntimeError("Update verification requires a frozen EXE and isolated data directory")
        from workbench.storage import Store
        from workbench.updater import launch_replacement
        store=Store();store.backup();store.db.close()
        source=Path(sys.argv[sys.argv.index("--verify-update")+1]).resolve()
        launch_replacement(source,restart_args=("--self-test",))
        return 0
    lock=QLockFile(str(data_dir()/"app.lock"));lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None,"订单跟进工作台","程序已经运行，请从系统托盘双击工作台图标打开。");return 0
    def exception_hook(kind,value,tb):
        (data_dir()/"error.log").write_text("".join(traceback.format_exception(kind,value,tb)),encoding="utf-8")
        QMessageBox.critical(None,"操作未完成",str(value)+"\n错误记录已保存到数据目录。")
    sys.excepthook=exception_hook
    window=MainWindow()
    if "--minimized" not in sys.argv or not QSystemTrayIcon.isSystemTrayAvailable():window.show()
    return app.exec()


if __name__=="__main__":
    sys.exit(main())
