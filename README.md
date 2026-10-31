# 订单跟进工作台

面向 Windows 的本地订单跟进桌面应用。初版 **v0.1.0**。

下载：[最新 Windows 版本](https://github.com/HVTMRZ-A/order-followup-desktop/releases/latest)

## 已实现

- 新订单手动登记与 Excel `.xlsx` / CSV 导入，模板导出、预览、重复订单拦截、整批事务保存。
- 订单、合同号、销售订单号及各自经办人关联。
- 整单或按型号确认工程 BOM、分析、包材信息及跟进完成。
- 合同接单满 24 小时未确认提高优先级；分析满 10 个自然日未确认包材信息提高优先级。
- 包材请购数量 = 对应型号产品数量 × 该包材单件用量（十进制定点计算）。
- 按填写的提醒日期在本机时间 09:00 提醒；未填写提醒日则采用预计到料日期；分批到料可累计登记。
- 分仓、成品入库、销售出库每日跟进记录；历史未解决事项持续显示。
- 系统托盘、可选开机启动、本地数据备份与恢复。
- 从公开 GitHub Release 检查更新、下载 SHA-256 校验、数据库自动备份、原子替换程序并重启。

## 使用

下载 ZIP 后解压到可写目录，运行 `OrderFollowup.exe`，无需安装 Python。
真实业务数据仅保存于 `%LOCALAPPDATA%\OrderFollowupDesktop`，不会上传至仓库或 GitHub。

工作台不操作云星空，不自动刷新外部系统；BOM、分析均为用户确认项。
09:00 准点提醒要求电脑开机且程序运行；未运行时打开程序补查。详见 [使用说明](docs/使用说明.md)。

## 开发与构建

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe main.py
.\.venv\Scripts\python.exe scripts/build.py
```

开发测试可设置 `ORDER_WORKBENCH_DATA` 指向独立测试目录。
发布时更新 `workbench/__init__.py` 的 `VERSION`，构建并在同名 GitHub Release 附上 `OrderFollowup.exe`、ZIP 和 `SHA256SUMS.txt`；正式 Release 的 EXE 资产须提供 GitHub SHA-256 digest。程序只接受固定仓库的正式三段式版本。

## 数据与设计

SQLite 存储结构版本为 1；订单包含型号与包材明细。配置、每日记录与保存历史独立保存。
整单确认是对当前全部型号的批量操作，新增型号不继承先前确认。整单完成由全部型号“跟进完成”汇总，撤销任一型号完成后恢复其提醒。
导入仅新增订单，已有订单不自动覆盖。接单日期仅填写日期时按当天 00:00 计算。

## 许可证

项目源码使用 MIT 许可证。Qt / PySide6 等第三方组件许可独立，见 [第三方说明](THIRD_PARTY_NOTICES.md)。
