# 设备监控系统 1.0.7.0 版本说明（README）

| 项目 | 内容 |
|---|---|
| 版本号 | **1.0.7.0** |
| 版本主题 | PyQt5 → PySide6 迁移版（Qt 6） |
| 发布日期 | 2026-11-13 |
| 运行环境 | Windows 10 1809+ / Windows 11，64 位 |
| 开发/打包环境 | Python 3.11.9 + PySide6 6.8.3 + shiboken6 6.8.3 |
| 前置版本 | 1.0.6.3（见 `发布说明_V1.0.6.3.md`） |
| 真机状态 | 代码迁移与静态/自动化验证已完成；**真机回归延后**，见“验证状态” |

---

## 1. 这版是什么

1.0.7.0 是把界面层从 **PyQt5 5.15** 迁移到 **PySide6 6.8（Qt 6）** 的版本。功能范围与 1.0.6.3 保持一致，目标不是加功能，而是：

- 去掉对 PyQt5 / Qt5 的运行时依赖；
- 改用官方 Qt for Python 绑定（LGPL 许可路径更清晰）；
- 为后续 Qt 6 版本升级留出空间。

界面文案、按钮布局、业务逻辑、日志格式、输出文件位置均未改变。存在差异的地方集中在 Qt 版本行为与运行环境要求，见第 3、4 节。

---

## 2. 本次迁移要点

### 2.1 代码层面

| 项目 | 变化 |
|---|---|
| 绑定库 | `PyQt5` → `PySide6`（全部 17 个 UI/线程文件） |
| 信号定义 | `pyqtSignal` → `Signal`（共 47 处） |
| 对话框执行 | `exec_()` → `exec()`（返回 `int`，与 `QDialog.DialogCode` 比较） |
| 动作类 | `QAction` 从 `QtWidgets` 移到 `QtGui` |
| 复选框 | `stateChanged(int)` → `checkStateChanged(Qt.CheckState)` |
| 枚举 | 全面改为作用域枚举，如 `Qt.AlignmentFlag.AlignLeft`、`QMessageBox.StandardButton.Yes`、`QHeaderView.ResizeMode.*`、`QFileDialog.Option.*` |
| 分割器 | `QSplitter(Qt.Vertical)` → `QSplitter(Qt.Orientation.Vertical)` |
| 跨线程信号 | 携带集合的信号改为 `Signal(object)`，避免 Qt6 不支持 `set` 类型 |

改动规模：17 个文件，+134 / −132 行。未改动 `service/`、`business/` 业务层与 `tools/`。

### 2.2 对用户可见的影响

1. **不再支持 Windows 7 / 8 / 8.1**：Qt 6 仅支持 Windows 10 1809 及以上、Windows 11（64 位）。
2. **外观基本不变**：QSS 样式未改；标题栏、按钮、表格、日志配色与 1.0.6.3 一致。
3. **高 DPI 行为按 Qt 6 默认**：缩放屏下控件尺寸由 Qt 6 处理，不再使用 Qt5 的高 DPI 开关。若现场使用 125%/150% 缩放，首次运行请核对窗口是否完整显示。
4. **启动依赖变化**：发布包内不再需要 Qt5 DLL，改为携带 Qt6 / PySide6 运行库；包体积与文件清单会变化。
5. **对话框返回值**：确认/取消逻辑已按 Qt6 枚举适配，行为与旧版一致（“是”执行、“否”不执行）。
6. **线程退出行为更严格**：关闭窗口时会按固定顺序停止监控、找卡、心跳、查询、信息刷新、开 ADB/清理线程并等待收尾。等待期间窗口可能短暂无响应，属收尾过程。

> 截图待补：1.0.7.0 启动后的主界面，与 1.0.6.3 截图并排对比（确认外观未变）。

---

## 3. 运行环境与依赖

### 3.1 最终用户（使用发布包）

| 项目 | 要求 |
|---|---|
| 系统 | Windows 10 1809+ / Windows 11，64 位 |
| 运行时 | 无需安装 Python；发布包已内置 |
| 目录 | 程序目录必须可写（输出写在 exe 同级） |
| 外部工具 | `tools\bin\` 随包分发（`adb.exe`、`plink.exe`、`pscp.exe`、`DeviceId.exe` 等） |
| 配置 | 根目录 `device_info.json` 必须存在 |

### 3.2 开发/源码运行

| 依赖 | 版本 |
|---|---|
| Python | 3.11.9（64 位） |
| PySide6 | 6.8.3 |
| shiboken6 | 6.8.3 |
| openpyxl | 3.1.2 |
| paramiko | 3.5.1 |
| cryptography | ≥ 3.3 |

说明：

- 仓库内已建立专用环境 `D:\log_monitor\20261019\.venv`（Python 3.11.9 + PySide6 6.8.3），不纳入 git（`.gitignore` 已含 `.venv/`）；
- 不使用旧环境 `D:\log_monitor\.venv_pyside6`（Python 3.14.2 + PySide6 6.10.3），仅作历史对照；
- `requirements.txt` 已同步为 `PySide6==6.8.3`（原 `PyQt5==5.15.9` 已移除），并已去掉 `pandas` 等不再使用的依赖。

```powershell
# 在仓库根目录创建/复用环境后执行
python -m pip install PySide6==6.8.3 openpyxl==3.1.2 paramiko==3.5.1 "cryptography>=3.3"
```

---

## 4. 启动方式

### 4.1 源码运行

```powershell
# 方式一：使用仓库内专用环境
D:\log_monitor\20261019\.venv\Scripts\python.exe main.py

# 方式二：先激活环境
.\.venv\Scripts\Activate.ps1
python main.py
```

启动后窗口最大化，标题栏显示“设备监控系统 V<版本号>”，状态栏左下角为“就绪”。

### 4.2 发布包运行

1. 解压发布压缩包到可写目录；
2. 双击 `log_monitor.exe`；
3. 首次运行若被 SmartScreen 拦截，选择“更多信息 → 仍要运行”。

> 打包说明：`log_monitor.spec` 已迁移到 PySide6/Qt6 口径（`hiddenimports` 为 PySide6 三模块，`excludes` 排除 PyQt5/PyQt6/tkinter/pandas 等，Qt 插件只保留 `platforms/qwindows`、`styles/qmodernwindowsstyle`、`imageformats/qgif|qico|qjpeg`）。本版仍为 **onefile + UPX**，构建与启动烟测均已通过。

### 4.3 自检命令（开发环境）

```powershell
python -m compileall -q .
python -m pytest tests -q
python -m pylint -E ui service business main.py
```

当前结果：compileall 通过；pytest 342 项通过（另 1 项跳过）；pylint -E 无错误；`main.py` 启动无 traceback、无 PyQt5 模块加载。

---

## 5. 目录结构要点

```
20261019/
├── main.py                       # 入口：创建 QApplication，调用 MainWindow
├── config.py                     # 路径、设备类型、端口、并发与开关（USE_UDP_DISCOVERY 等）
├── device_info.json              # 按型号的初始化/发送节目配置（型号增删只改此文件）
├── device_config.py              # device_info.json 的加载与查询
├── data_models.py                # DeviceState / MonitorConfig / OperationResult
├── ui/
│   ├── main_window.py            # 主窗口：组件组装、信号路由、任务编排、关窗收尾
│   ├── control_panel.py          # 顶部控制面板（三行按钮/参数）
│   ├── device_list_view.py       # 设备表格（列显示、排序、全选、右键复制）
│   ├── result_display_view.py    # 彩色日志面板（导出/清空/右键）
│   ├── device_refresh_controller.py  # 找卡调度（UDP / DeviceId.exe）
│   ├── monitor_thread.py         # 监控线程（首检、轮询、停止等待）
│   ├── serial_query_manager.py   # 查询调度（安卓并行 / Linux 串行池）
│   ├── reflash_device_threadpool.py  # 设备信息补全线程池（8 并发/队列 512）
│   ├── workers/                  # 找卡、心跳、开 ADB、清历史等后台任务
│   └── dialogs/                  # 监控确认、清历史、开关机初始化、发送节目
├── service/                      # 工具/传输/日志/文件服务（adb、ssh、协议）
├── business/                     # 监控、日志、截图、查询分发等业务逻辑
├── tools/
│   ├── bin/                      # adb / plink / pscp / DeviceId / HPassword
│   └── *.sh, *.rc                # 设备端脚本与初始化配置
├── tests/                        # pytest 用例
├── output/                       # 运行产物：logs / excel / screenshot / switch_log / data
├── result_log/                   # 手工导出的日志面板
├── program/                      # 节目包（默认 {型号}_project.tar.gz，缺省时需手工指定）
├── 用户手册.md
├── 设备监控系统操作手册.md
├── README_1.0.7.0.md             # 本文件
├── CHANGELOG.md
└── 发布说明_V1.0.7.0.md          # 本版发布说明（上一版为 发布说明_V1.0.6.3.md）
```

要点：

- `output/`、`result_log/`、`switch_log/`、`device_monitoring_data.json`、`device_error.txt` 都是运行期产物，不要提交到仓库；
- 型号差异只应体现在 `device_info.json`，代码不应出现型号分支；
- `tools/bin` 为必需运行资产，发布包必须完整携带。

---

## 6. 已知限制

1. **真机回归未完成**：本轮只完成代码迁移与静态/自动化验证。找卡、查询、截图、发送节目、开关机初始化、ADB、长时间监控，均需在真机环境逐项回归。
2. **无串口找卡**：找卡只有 UDP 9527 与 `DeviceId.exe` 两个通道；不存在 RS-232/RS-485 串口通道。
3. **日志面板无筛选/搜索**：只有全选、复制、删除、清空与导出。
4. **型号清单缺口**：`device_info.json` 含 `D36`，但 `config.py` 的支持类型不含 `D36`；`Q910` 在支持类型中但 `device_info.json` 无配置。两者都会导致对应型号无法正常刷新或无法执行初始化/发送节目。
5. **停止监控会等待当前轮**：点击“停止监控”后界面可能无响应直至本轮设备处理结束（线程在 UI 线程内 `wait()`）。
6. **启动即重置会话数据**：每次启动或切换设备类型会清空 `device_monitoring_data.json`、`device_error.txt` 与四类监控日志；只有 `output\task_checkpoint.json` 跨启动保留。
7. **单文件打包与 LGPL**：onefile 形式下用户替换 Qt/PySide6 库不直观，需按第 8 节提供合规材料。

> 待真机确认：高 DPI（125%/150%/200%）下的窗口布局、对话框按钮裁切、表格行高；Windows 10 1809 最低版本的实际启动情况。

---

## 7. 验证状态

| 项目 | 状态 |
|---|---|
| 全量静态检查（`compileall`） | 通过 |
| 单元测试（pytest） | 342 项通过（另 1 项跳过） |
| `pylint -E` | 无错误 |
| UI 模块导入（22 个） | 通过 |
| 离屏启动（无窗口，4 秒） | 进程存活，无 traceback |
| 真实窗口启动（2 秒退出） | 退出码 0 |
| 运行时 PyQt5 加载 | 0 |
| PySide6/Qt6 打包（onefile + UPX） | 通过，`log_monitor.exe` 27.51 MB |
| Qt 插件加载 | 仅 `qwindows` / `qmodernwindowsstyle` / `qgif|qico|qjpeg`，无加载失败 |
| 发布包启动烟测（release 目录与 zip 解压后各一次） | 进程存活，`app.log` 无 ERROR，随包 adb 生效 |
| 真机功能回归 | **未执行（延后）** |
| 打包与安装包验证 | **已完成**（zip 31.82 MB） |

真机回归建议按以下顺序，并在每步记录结果：

1. 找卡：广播 + 手动目标（单 IP / 区间 / CIDR）；
2. 信息补全与热插拔（拔插网线观察上下线）；
3. 查询类五个按钮，含 Linux 与安卓各一台；
4. 截图、校时、开关机次数、导出/清空计数；
5. 开关机初始化与发送节目（先用 1 台样机）；
6. 开启 ADB；
7. 监控 30 分钟以上，中途停止/重启，检查日志与 Excel；
8. 监控运行中关窗、查询运行中关窗；
9. 高 DPI 与多屏；
10. 打包产物在干净机器上启动。

---

## 8. 许可与 LGPL 随包要求

### 8.1 本项目许可

本项目为深圳市灰度科技股份有限公司内部资产，采用**公司内部使用许可（All Rights Reserved）**，全文见仓库根目录 `LICENSE`，仅授权公司内部人员按职务使用。该许可仅覆盖本项目代码，不覆盖第三方组件；第三方组件许可与声明见根目录 `THIRD-PARTY-NOTICES`。

### 8.2 第三方组件

| 组件 | 许可 | 说明 |
|---|---|---|
| PySide6 | LGPLv3 / GPLv3 / 商业许可 | 本版按 **LGPLv3** 使用 |
| Qt 6 | LGPLv3 / GPLv3 / 商业许可 | PySide6 随附的 Qt 运行库同样按 LGPLv3 使用 |
| shiboken6 | LGPLv3 | PySide6 的绑定生成运行时 |
| paramiko / cryptography / openpyxl | LGPL / Apache-2.0 / MIT | 按各自许可证随包保留声明 |

### 8.3 发布包必须携带

1. **LGPLv3 许可证全文**（以及 GPLv3 全文，LGPLv3 以其为基础）；
2. Qt 与 PySide6 的**版权声明与许可说明**（来自 PySide6 发行包的 `LICENSES/` 目录）；
3. 本项目 `LICENSE`（公司内部使用许可）与 `THIRD-PARTY-NOTICES`（第三方组件声明）；
4. 第三方组件许可清单（上表内容即可作为初稿）。

### 8.4 LGPLv3 合规要点

- **动态链接**：Qt/PySide6 以动态库形式使用，不得静态链接后闭源分发；
- **可替换性**：必须让接收者能够替换/重新链接 LGPL 库。onefile 打包需提供可行方式（例如同时提供非 onefile 的目录版，或提供重新打包脚本与构建说明）；
- **源码获取**：随包提供对应版本的 PySide6/Qt 源码获取方式，或提供有效期不少于三年的书面要约；
- **声明保留**：不得移除包内的版权、许可与第三方声明；
- **修改义务**：如修改了 Qt/PySide6 本身，修改部分需按 LGPLv3 开源。

> 发布形态：沿用既有的 **onefile + UPX**（与 1.0.6.3 一致），不改 onedir。onefile 会把运行库解压到临时目录，启动略慢，换取单文件分发；法务对 LGPL“可替换性”的具体要求仍待确认，合规文本与流程图待补齐。

---

## 9. 从 1.0.6.3 升级到 1.0.7.0

1. 备份旧版目录（至少保留 `output\`、`switch_log\`、`device_error.txt`）；
2. 用 1.0.7.0 发布包替换程序文件，**保留** `device_info.json` 中现场新增的型号配置；
3. 确认 `tools\bin\` 完整；
4. 首次启动按第 5 节核对目录与输出；
5. 按第 7 节真机回归清单抽查关键链路。

回退：直接用 1.0.6.3 包覆盖程序文件即可；`output\` 与 `device_info.json` 格式未变，可继续使用。

### 相关文档

- 界面与日常用法：`用户手册.md`
- 现场操作与异常处置：`设备监控系统操作手册.md`
- 上一版发布信息：`发布说明_V1.0.6.3.md`
- 变更记录：`CHANGELOG.md`
