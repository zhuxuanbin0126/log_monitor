# 更新日志

本项目采用四段版本号：`主.次.修订.构建`，与 `config.VERSION`、`version_info.txt`、Git tag 保持一致。

## v1.0.6.0 (2026-10-20)

### 新增

- ADB 状态列与 Android 设备网络 ADB 自动开启
- ADB 开启后自动回读 MAC / 设备名 / 系统 / 版本信息
- 查询流程支持 ADB 并行处理与设备级状态信号
- 监控“清除历史数据”选项（恢复历史交互入口）
- 统一日志服务：`output/logs/app.log` 轮转，替代服务层散落 `print`
- 设备传输层抽象 `IDeviceTransport`，ADB / SSH 可替换；SSH 优先使用 paramiko
- 任务控制：`中断任务`（查询/控制/清理/开 ADB/监控全覆盖）+ `继续执行上一个任务`（断点续跑，检查点落盘，重启后可续）
- 设备列表 ADB 拆分为「网络ADB / 有线ADB」两列
- 手动找卡改为使能开关（单 IP / 区间 / CIDR / 组合），格式错误回显完整范例
- Linux 设备校时改走 SSH 直设本机时间（`date -s` + `hwclock -w` + epoch 校验）
- 离线设备处理：派发前秒级 TCP 探测跳过、任务结束自动补跑、汇总单列「离线未完成」

### 变更

- `MainWindow` 拆分：错误日志、Excel 导出、设备刷新、查询结果展示独立为组件
- `device_config` 封装为 `DeviceConfigRepository`，支持显式 `reload()`
- 业务操作（初始化 / 校时 / 节目发送 / 截图）统一返回 `OperationResult`
- 查询策略分发表下沉到 `business/query_dispatcher.py`
- 串行查询的进度计数、CSV 写入增加线程锁
- 并发分池：协议池 16 / adb-SSH 池 4 / Linux SSH 池 4 / 截图 16，滑动窗口派发
- Linux 文件传输改 SFTP 复用连接；清空开关机、初始化、发送节目合并往返
- 日志逐行着色、关键节点带系统时间、汇总带耗时统计

### 修复

- `H16` 未纳入 Android 设备分类，导致其误走 SSH 回退
- 开关机初始化 chmod 误报 `device not found`（改走协议 exec 优先的统一命令通道）
- 并行任务下 `adb disconnect` 全局断连误伤其它设备
- 「无法获取」被误判为查询失败；Q910 未识别；心跳日志刷屏

### 工程化

- 新增 `tests/`（pytest）与 `.github/workflows/pytest.yml`、`pylint.yml`、`release.yml`
- 新增 `requirements-dev.txt`、`.pylintrc`
- 新增 `tools/build_release.py`：版本校验、打包、SHA256 清单、ZIP
- 删除失效的 `pyinstaller_spec.py`，以 `log_monitor.spec` 为唯一打包真源
- 删除已弃用的 `ui/query_thread.py`、`ui/reflash_device_thread.py`
- 仓库移除 `pyc`、exe 构建产物与运行数据，入库体积由约 116 MB 降至约 9.5 MB
- Excel 导出改 openpyxl 直写，移除 pandas/numpy；打包剔除 Qt 翻译、QML、opengl32sw 等无用资源（exe 约 32 MB）

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
