# 设备监控系统 (Log Monitor)

基于PyQt5的专业设备监控桌面应用程序，支持设备发现、SSH连接、实时监控、数据记录、异常告警和屏幕截图等完整功能。

## 🚀 核心功能

### 1. 设备自动发现与管理
- **智能设备发现**：自动调用DeviceId.exe扫描网络设备
- **多设备类型支持**：支持A-B-C-D-H、A3L、A4L、A5L、A6L、B6L、B8L、C08L、C16H、C16L、C16、D16、H4K、H6、H8等多种设备类型
- **设备信息完善**：自动获取设备MAC地址、设备名称等详细信息

### 2. 实时监控与数据采集
- **时间同步监控**：实时监控设备时间与本地时间差异，支持阈值告警
- **运行状态监控**：监控设备运行时长、启动时间、启动次数等关键指标
- **自定义监控项**：可选择监控时间、启动状态、启动次数等不同维度

### 3. 数据记录与导出
- **多格式日志**：自动生成cardtime.log、uptime.log、startcount.log、comprehensive.log等日志文件，存储在output/logs目录
- **Excel导出**：监控结果自动导出为Excel表格，支持追加模式和自动列宽调整，存储在output/excel目录
- **错误日志**：自动记录设备异常到device_error.txt，支持自动打开查看

### 4. 智能错误处理
- **密码认证优化**：密码认证失败时显示友好提示"设备通信异常: 密码认证失败，请检查设备密码配置"
- **错误类型识别**：自动识别时间同步异常、启动次数异常、设备离线、通信超时、认证失败等错误类型
- **重试机制**：关键操作支持3次重试，提高操作成功率
- **设备授权处理**：遇到"device unauthorized"错误时，自动通过SSH执行命令重启ADB服务，解决授权问题

### 5. 用户友好界面
- **现代化UI**：基于PyQt5的现代化图形界面
- **实时状态显示**：状态栏实时显示监控状态和设备数量
- **彩色日志**：正常消息(黑色)、警告消息(黄色)、错误消息(红色)
- **批量操作**：支持设备多选、全选、批量查询和监控
- **屏幕截图**：支持对安卓设备进行屏幕截图，可在监控时自动截图或手动触发截图

### 6. 自动截图功能
- **支持的设备类型**：H6、H8、H4K、B6L、B8L、A4L、A5L、A6L、C16H
- **截图保存路径**：存储在output/screenshot目录，按设备ID分类
- **自动与手动模式**：监控时自动截图或手动触发截图
- **授权问题处理**：自动解决设备未授权问题，提高截图成功率

## 📦 项目结构

```
log_monitor/
├── service/                       # 服务层 - 基础工具服务
│   ├── tool_service.py           # 工具门面：命令执行、SSH、设备密码、ADB 委托
│   ├── adb_service.py            # ADB 操作：连接、推送、拉取、MD5、权限
│   ├── adb_device_manager.py     # ADB 状态管理：分类、缓存、连接池、批量开启
│   ├── device_utils.py           # 共享工具：命令执行、MD5、设备分类、重试装饰器
│   ├── transports.py             # 传输层抽象：ADB / SSH 可替换实现
│   ├── logging_service.py        # 统一日志：文件轮转 + 开发态控制台
│   ├── data_processing_service.py # 数据处理：运行时间解析、错误消息格式化
│   └── file_service.py           # 文件服务：日志读写、错误记录、数据持久化
├── business/                     # 业务层 - 核心业务逻辑
│   ├── device_monitor_service.py # 设备监控业务：状态检查、错误检测、校时、节目发送
│   ├── device_log_service.py     # 开关机计数、日志清理与导出
│   ├── screenshot_service.py     # 屏幕截图
│   └── query_dispatcher.py       # 查询/操作策略分发表
├── ui/                           # 视图层 - 用户界面组件
│   ├── main_window.py            # 主窗口：组装视图与信号路由
│   ├── device_refresh_controller.py # 设备刷新控制器
│   ├── error_log_manager.py      # 错误分类、落盘与查看
│   ├── excel_exporter.py         # 监控结果 Excel 导出
│   ├── query_result_presenter.py # 查询结果与汇总展示
│   ├── dialogs/                  # 确认对话框（开关机初始化、发送节目）
│   ├── device_list_view.py       # 设备列表视图：设备展示和选择
│   ├── control_panel.py          # 控制面板：监控设置和设备类型选择
│   ├── result_display_view.py    # 结果显示视图：彩色日志显示
│   ├── monitor_thread.py         # 监控线程：后台监控任务
│   ├── serial_query_manager.py   # 串行/并行查询管理器
│   ├── reflash_device_threadpool.py # 设备刷新线程池
│   └── base_window.py            # 基础窗口类
├── tools/                         # 工具脚本和配置文件
│   ├── boot_counter.sh           # 开关机计数器脚本
│   ├── getdeviceinfo.sh          # 设备信息获取脚本
│   ├── init.huidu.rc             # 初始化配置文件
│   ├── init.rk356x.rc            # 初始化配置文件
│   ├── ntpdate                   # 时间同步工具
│   └── run.sh                    # 运行脚本
├── output/                        # 输出目录
│   ├── logs/                     # 日志文件目录
│   ├── excel/                    # Excel文件目录
│   └── screenshot/               # 截图文件目录
├── config.py                     # 配置文件：路径、阈值、设备类型配置
├── device_config.py              # 设备型号配置加载（device_info.json）
├── data_models.py                # 数据模型：DeviceState / MonitorConfig / OperationResult
├── main.py                       # 应用程序入口
├── requirements.txt              # Python 运行依赖
├── requirements-dev.txt          # 测试与静态检查依赖
├── package.bat                   # Windows 一键打包脚本
├── log_monitor.spec              # PyInstaller 打包配置（唯一真源）
├── tests/                        # pytest 单元测试
├── .github/workflows/            # CI：pytest + pylint + release
├── CHANGELOG.md                  # 版本变更记录
└── README.md                     # 项目说明文档
```

## 🛠️ 技术架构

### 三层架构设计
1. **服务层(Service)**：提供基础工具能力，与系统命令和外部工具交互
2. **业务层(Business)**：实现核心监控逻辑和数据处理
3. **视图层(UI)**：提供用户界面和交互控制

### 多线程设计
- **主线程**：UI渲染和用户交互
- **监控线程**：后台设备监控任务
- **查询管理器**：ADB 设备并行、SSH 设备串行，避免连接冲突

### 错误处理机制
- 结构化错误信息（`OperationResult`）
- 错误类型自动识别
- 错误日志自动记录和查看
- 统一日志文件 `output/logs/app.log`（5 MB × 3 轮转）

### 工程化与发布
```bash
python -m pytest tests -q                  # 单元测试
python tools/build_release.py --check-only # 版本一致性校验
python tools/build_release.py              # 打包 + SHA256 + zip
```

## 📋 系统要求

### 开发环境
- Python 3.11（推荐，CI 同版本）
- Windows 7/10/11
- 网络连接（用于设备通信）

### 运行时依赖
```bash
# 核心Python包
PyQt5==5.15.9    # 图形界面框架
pandas==2.1.0    # 数据处理和Excel导出
openpyxl==3.1.2  # Excel文件操作
paramiko==3.5.1  # SSH（不可用时自动回退 plink）

# 内置工具（位于 tools/bin，随发布包一起分发）
DeviceId.exe     # 设备发现工具
adb.exe          # Android 调试桥
plink.exe        # SSH 连接工具
pscp.exe         # 文件传输工具
```

## 🚀 快速开始

### 方式一：源码运行（开发模式）
```bash
# 1. 克隆或下载项目
cd <项目目录>

# 2. 安装Python依赖
pip install -r requirements.txt

# 3. 运行应用程序
python main.py
```

### 方式二：打包分发（生产环境）
```bash
# 一键打包 + 校验 + 发布包（推荐）
python tools/build_release.py

# 或仅调用 PyInstaller（产物在 dist/log_monitor.exe）
pip install pyinstaller
pyinstaller log_monitor.spec
```

### 方式三：Python包安装
```bash
# 安装到Python环境
pip install .

# 运行应用程序
log-monitor-gui
```

## 📊 使用指南

### 基本操作流程
1. **启动应用**：运行log_monitor.exe或python main.py
2. **选择设备类型**：从下拉框选择要监控的设备类型
3. **刷新设备列表**：点击"刷新设备列表"扫描网络设备
4. **选择设备**：在设备列表中选择要监控的设备（支持多选）
5. **设置监控选项**：选择要监控的项目（时间、启动状态、启动次数）
6. **开始监控**：设置监控间隔，点击"开始监控"
7. **查看结果**：在结果显示区域查看实时监控数据

### 监控配置选项
- **时间监控**：监控设备时间同步状态，时间差阈值可在config.py中配置
- **启动状态监控**：监控设备运行时长和启动时间
- **启动次数监控**：监控设备启动次数（部分设备类型不支持）
- **获取运行画面**：监控时自动对支持的设备进行屏幕截图
- **监控间隔**：可设置10-3600秒的监控频率
- **清除历史数据**：勾选后会清除之前的监控数据和日志文件

### 监控摘要
- **设备状态统计**：显示总设备数、在线设备数、离线设备数、错误设备数
- **时间异常设备**：列举时间差较大的设备及其偏差值
- **截图失败设备**：列举截图失败的设备
- **数据获取失败设备**：列举设备时间、启动时间、启动次数获取失败的设备

### 错误处理
- **密码认证失败**：自动优化提示信息，建议检查设备密码配置
- **设备离线**：自动检测并记录离线设备
- **通信异常**：支持重试机制，提高操作成功率
- **错误查看**：错误日志自动保存到device_error.txt，并可自动打开查看
- **设备授权处理**：遇到"device unauthorized"错误时，自动通过SSH执行命令重启ADB服务

### 屏幕截图功能
- **支持的设备类型**：H6、H8、H4K、B6L、B8L、A4L、A5L、A6L、C16H
- **截图保存路径**：
  - 主目录：`./output/screenshot`
  - 子目录：`./output/screenshot/设备ID`
  - 文件名格式：`设备ID_yyyy_MM_dd_hh_mm_ss.jpg`
- **使用方法**：
  - 监控时截图：在监控控制区域勾选"获取运行画面"选项
  - 手动截图：在查询/控制区域点击"截图"按钮
- **错误提示**：对于不支持的设备，会显示统一的错误提示："设备XX不支持通过adb截图"
- **授权问题处理**：自动解决设备未授权问题，提高截图成功率

## 📁 文件说明

### 配置文件 (config.py)
- `get_base_dir(dev_type)`：获取设备类型对应的日志目录
- `time_diff_threshold`：启动时间误差阈值（默认120秒）
- `daily_time_diff_threshold`：设备时间日均误差阈值（默认3秒）
- `error_log_file`：错误日志文件路径

### 数据文件
- `device_monitoring_data.json`：设备监控数据持久化存储
- `device_error.txt`：设备错误日志记录
- `output/logs/目录`：包含cardtime.log、uptime.log、startcount.log、comprehensive.log等日志文件
- `output/excel/目录`：存储监控结果的Excel文件
- `output/screenshot/目录`：按设备ID分类的截图文件

## 🔧 打包部署

### 自动打包（推荐）
```bash
# 版本校验 → PyInstaller → release/ 运行时资源 → SHA256SUMS.txt → zip
python tools/build_release.py

# 只校验版本一致性
python tools/build_release.py --check-only

# 跳过 zip（仅生成 release 目录）
python tools/build_release.py --no-zip
```

### 手动打包
```bash
pip install pyinstaller
pyinstaller log_monitor.spec
```

### 发布包内容
`release/` 目录包含：
- `log_monitor.exe`：主应用程序
- `tools/bin/`：DeviceId.exe、adb.exe、plink.exe、pscp.exe、HPassword.exe、HSDKCmd.exe 及 DLL
- `tools/`：设备端脚本（boot_counter.sh、ntpdate、init.*.rc 等）
- `device_info.json`：设备型号配置
- `README.md`、`用户手册.md`、`用户手册.pdf`、`CHANGELOG.md`
- `SHA256SUMS.txt`：逐文件 SHA256 校验清单
- `log_monitor_vX.Y.Z.W.zip`：完整发布压缩包

## 🐛 常见问题

### Q1: 程序无法启动
**A**: 确保 `tools/bin` 目录完整（adb.exe、AdbWinApi.dll、AdbWinUsbApi.dll、DeviceId.exe 等），且与主程序同级。

### Q2: 设备列表为空
**A**: 检查DeviceId.exe是否能正常运行，网络连接是否正常，设备是否在线

### Q3: SSH连接失败
**A**: 检查设备密码配置，确保plink.exe可用，网络连接是否正常

### Q4: 监控数据不更新
**A**: 检查设备网络连接，尝试调整监控间隔，确保设备密码正确

### Q5: Excel导出失败
**A**: 确保有写入权限，检查pandas库是否正常安装，确保output/excel目录存在

### Q6: 截图失败
**A**: 检查设备是否支持截图（仅支持H6、H8、H4K、B6L、B8L、A4L、A5L、A6L、C16H），确保adb.exe和相关DLL文件存在

### Q7: 设备未授权错误
**A**: 程序会自动处理此问题，通过SSH执行命令重启ADB服务，无需手动干预

## 📝 更新日志

### v1.0.6.0 (当前版本)
- ✅ 新增 ADB 状态列，展示设备 ADB 开启情况
- ✅ Android 设备 ADB 自动开启，开启后自动回读 MAC/设备名/系统/版本信息
- ✅ 查询流程支持 ADB 并行处理，并新增设备级状态信号
- ✅ 服务层拆分：ADBService / DeviceUtils / ADBDeviceManager / ScreenshotService / DeviceLogService
- ✅ 引入数据模型（OperationResult / DeviceState / MonitorConfig / QueryType）与统一重试装饰器
- ✅ 回补 requirements.txt，统一工程配置与版本号
- ✅ 清理入库的构建产物与运行数据，修正 .gitignore 规则

### v1.0.3.0
- ✅ 设备自动发现和列表管理
- ✅ 多维度实时监控功能
- ✅ 智能错误处理和友好提示
- ✅ Excel数据导出功能
- ✅ 现代化图形界面
- ✅ 完整的打包部署方案
- ✅ 屏幕截图功能，支持对安卓设备进行屏幕截图
- ✅ 自动处理设备未授权问题
- ✅ 监控摘要功能，显示设备状态统计和异常设备列表
- ✅ 统一的输出目录结构，所有文件存储在output文件夹中

### 近期优化
- 密码认证失败提示优化
- 错误日志自动打开功能
- 红色错误消息显示
- 重试机制增强
- 时间差计算优化
- 新增屏幕截图功能，支持对安卓设备进行屏幕截图
- 支持监控时自动截图和手动触发截图
- 按设备ID和时间自动组织截图文件
- 自动处理设备未授权问题，提高截图成功率
- 监控摘要功能，显示设备状态统计和异常设备列表
- 统一的输出目录结构，所有文件存储在output文件夹中
- 修复Excel导出时目录不存在的问题
- 优化打包脚本，减小可执行文件体积

## 📞 技术支持

如遇问题，请检查：
1. 所有必需.exe文件是否齐全
2. 网络连接是否正常
3. 设备密码配置是否正确
4. 查看device_error.txt获取详细错误信息

## 📄 许可证

本项目采用**木兰宽松许可证，第2版（MulanPSL-2.0）**，可自由使用和修改。

许可证全文见仓库根目录 [LICENSE](LICENSE)，或参见 <http://license.coscl.org.cn/MulanPSL2>。

---
**注意**：请确保遵守公司网络安全规定，合理使用设备监控功能。