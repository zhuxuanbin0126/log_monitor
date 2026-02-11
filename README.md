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
│   ├── tool_service.py           # 工具服务：命令执行、SSH连接、设备密码获取、ADB操作
│   ├── data_processing_service.py # 数据处理：运行时间解析、错误消息格式化
│   └── file_service.py           # 文件服务：日志读写、错误记录、数据持久化
├── business/                     # 业务层 - 核心业务逻辑
│   └── device_monitor_service.py # 设备监控业务：设备状态检查、错误检测、截图功能
├── ui/                           # 视图层 - 用户界面组件
│   ├── main_window.py            # 主窗口：协调各组件、错误处理、监控控制
│   ├── device_list_view.py       # 设备列表视图：设备展示和选择
│   ├── control_panel.py          # 控制面板：监控设置和设备类型选择
│   ├── result_display_view.py    # 结果显示视图：彩色日志显示
│   ├── monitor_thread.py         # 监控线程：后台监控任务
│   ├── query_thread.py           # 查询线程：单个设备查询任务
│   ├── reflash_device_thread.py  # 设备刷新线程
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
├── main.py                       # 应用程序入口
├── requirements.txt              # Python依赖包
├── build_simple.bat              # Windows打包脚本
├── DeviceId.exe                  # 设备发现工具
├── bash.exe                      # Bash命令行工具
├── grep.exe                      # 文本搜索工具
├── plink.exe                     # SSH连接工具
├── pscp.exe                      # 文件传输工具
├── adb.exe                       # Android调试桥工具
├── AdbWinApi.dll                 # ADB Windows API
├── AdbWinUsbApi.dll              # ADB Windows USB API
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
- **查询线程**：单个设备查询任务

### 错误处理机制
- 结构化错误信息
- 错误类型自动识别
- 错误日志自动记录和查看

## 📋 系统要求

### 开发环境
- Python 3.8+
- Windows 7/10/11
- 网络连接（用于设备通信）

### 运行时依赖
```bash
# 核心Python包
PyQt5==5.15.9    # 图形界面框架
pandas==2.1.0    # 数据处理和Excel导出
openpyxl==3.1.2  # Excel文件操作

# 内置工具（已包含在发布包中）
DeviceId.exe     # 设备发现工具
bash.exe         # 命令行工具
grep.exe         # 文本搜索工具
plink.exe        # SSH连接工具
```

## 🚀 快速开始

### 方式一：源码运行（开发模式）
```bash
# 1. 克隆或下载项目
cd d:\log_monitor

# 2. 安装Python依赖
pip install -r requirements.txt

# 3. 运行应用程序
python main.py
```

### 方式二：打包分发（生产环境）
```bash
# 使用提供的打包脚本（推荐）
build.bat

# 或手动使用PyInstaller
pip install pyinstaller
pyinstaller --onefile --windowed --add-data "DeviceId.exe;." --add-data "*.exe;." main.py
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

### 自动打包
```bash
# 使用提供的build_simple.bat脚本（推荐）
build_simple.bat
```

### 手动打包选项
```bash
# 单个可执行文件（包含所有依赖）
pyinstaller --onefile --windowed --add-data "DeviceId.exe;" --add-data "bash.exe;" --add-data "grep.exe;" --add-data "plink.exe;" --add-data "pscp.exe;" --add-data "adb.exe;" --add-data "AdbWinApi.dll;" --add-data "AdbWinUsbApi.dll;" --add-data "config.py;" --hidden-import "pandas" --hidden-import "openpyxl" --hidden-import "PyQt5.QtWidgets" --hidden-import "PyQt5.QtCore" --hidden-import "PyQt5.QtGui" --upx --exclude-module "tkinter" main.py

# 包含控制台窗口（调试模式）
pyinstaller --onefile --console --add-data "*.exe;" --add-data "*.dll;" main.py

# 生成目录分发（便于调试）
pyinstaller --onedir --windowed --add-data "*.exe;" --add-data "*.dll;" main.py
```

### 发布包内容
打包后的release目录包含：
- `log_monitor.exe`：主应用程序
- `DeviceId.exe`：设备发现工具
- `bash.exe`：命令行工具
- `grep.exe`：文本搜索工具
- `plink.exe`：SSH连接工具
- `pscp.exe`：文件传输工具
- `adb.exe`：Android调试桥工具
- `AdbWinApi.dll`：ADB Windows API
- `AdbWinUsbApi.dll`：ADB Windows USB API
- `config.py`：配置文件
- `README.md`：说明文档
- 各设备类型日志目录

## 🐛 常见问题

### Q1: 程序无法启动
**A**: 确保所有.exe工具文件与主程序在同一目录下，特别是adb.exe、AdbWinApi.dll和AdbWinUsbApi.dll

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

### v1.0.2.3 (当前版本)
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

本项目采用MIT许可证，可自由使用和修改。

---
**注意**：请确保遵守公司网络安全规定，合理使用设备监控功能。