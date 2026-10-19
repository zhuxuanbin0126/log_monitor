# 更新日志

本项目采用四段版本号：`主.次.修订.构建`，与 `config.VERSION`、`version_info.txt`、Git tag 保持一致。

## v1.0.6.0 (2026-10-19)

### 新增

- ADB 状态列与 Android 设备网络 ADB 自动开启
- ADB 开启后自动回读 MAC / 设备名 / 系统 / 版本信息
- 查询流程支持 ADB 并行处理与设备级状态信号
- 监控“清除历史数据”选项（恢复历史交互入口）
- 统一日志服务：`output/logs/app.log` 轮转，替代服务层散落 `print`
- 设备传输层抽象 `IDeviceTransport`，ADB / SSH 可替换；SSH 优先使用 paramiko

### 变更

- `MainWindow` 拆分：错误日志、Excel 导出、设备刷新、查询结果展示独立为组件
- `device_config` 封装为 `DeviceConfigRepository`，支持显式 `reload()`
- 业务操作（初始化 / 校时 / 节目发送 / 截图）统一返回 `OperationResult`
- 查询策略分发表下沉到 `business/query_dispatcher.py`
- 串行查询的进度计数、CSV 写入增加线程锁

### 修复

- `H16` 未纳入 Android 设备分类，导致其误走 SSH 回退

### 工程化

- 新增 `tests/`（pytest）与 `.github/workflows/pytest.yml`、`pylint.yml`、`release.yml`
- 新增 `requirements-dev.txt`、`.pylintrc`
- 新增 `tools/build_release.py`：版本校验、打包、SHA256 清单、ZIP
- 删除失效的 `pyinstaller_spec.py`，以 `log_monitor.spec` 为唯一打包真源
- 删除已弃用的 `ui/query_thread.py`、`ui/reflash_device_thread.py`
- 仓库移除 `pyc`、exe 构建产物与运行数据，入库体积由约 116 MB 降至约 9.5 MB

## v1.0.5.0

- 引入 `data_models.py`（DeviceState / MonitorConfig / OperationResult / QueryType）
- 拆分 `ADBService`、`DeviceUtils`、`ADBDeviceManager`、`ScreenshotService`、`DeviceLogService`
- 确认对话框抽取到 `ui/dialogs/`
- 配置常量集中化与系统类型远程路径映射

## v1.0.4.0

- 新增 H16 / H20 设备支持
- 补充 `device_config.py` 与发布压缩包

## v1.0.3.0

- 引入 `SerialQueryManager` 串行查询与设备级状态
- 新增 `device_checker.py` 命令行体检工具
- 设备型号配置迁移到 `device_info.json`，新增型号无需改代码
