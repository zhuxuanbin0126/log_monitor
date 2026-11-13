# -*- coding: utf-8 -*-

"""启动时把随包工具目录补进**当前进程**的 PATH（静默、可失败、不影响主流程）。

定位：**兼容补充**。程序内部所有 adb 调用已固定走 ``service.device_utils.ADB_CMD``
（随包 ``tools/bin/adb.exe`` 的绝对路径），不依赖 PATH；本模块只解决
"本次运行期间由本程序拉起的其它工具/脚本裸调 ``adb`` 时命中系统里另一个 adb"的问题。

约束（按需求）：
- **只改当前进程的 ``os.environ['PATH']``**：不写注册表、不广播 ``WM_SETTINGCHANGE``、
  不改系统/用户环境变量，因此也就不需要管理员权限，且不会影响机器上的其它程序；
- 不向结果面板写日志、不弹窗；
- 不参与主流程耗时：由 ``main.py`` 放到守护线程里执行；
- 已有则不做任何动作；任何异常都只记一行 app.log 后降级为"不处理"。
"""

import ntpath
import os

from .logging_service import get_logger

logger = get_logger(__name__)


def _norm(path: str) -> str:
    """按 **Windows 路径语义** 规范化目录，用于 PATH 条目比较。

    本模块只服务 Windows（随包 ``tools/bin/*.exe``、PATH 以 ``;`` 分隔），因此这里
    显式使用 :mod:`ntpath` 而不是 :mod:`os.path`：反斜杠归一、大小写折叠、去掉尾部
    分隔符的行为在 Windows / Linux 宿主机上完全一致，避免测试或 CI 随宿主平台漂移。
    """
    if not path:
        return ""
    expanded = os.path.expandvars(path.strip())
    return ntpath.normcase(ntpath.abspath(expanded)).rstrip("\\")


def _split(value: str):
    return [p.strip().strip('"') for p in (value or "").split(";") if p.strip()]


def _prepend_process_path(target: str) -> str:
    """把 ``target`` 前置到当前进程 PATH（已包含则零动作）。

    Returns:
        ``'added'``：本次已注入；``'present'``：本来就包含，未做任何修改。
    """
    current = os.environ.get("PATH", "")
    if _norm(target) in {_norm(p) for p in _split(current)}:
        return "present"
    os.environ["PATH"] = target + (";" + current if current else "")
    return "added"


def ensure_tools_on_path(target_dir=None) -> dict:
    """确保 ``target_dir``（默认随包 ``tools/bin``）在**当前进程** PATH 中。

    返回值用于测试与日志：``action`` ∈ ``present`` / ``added`` / ``skipped-missing``。
    """
    from .device_utils import EXTERNAL_TOOLS_DIR  # 避免循环导入

    target = os.path.normpath(target_dir or EXTERNAL_TOOLS_DIR)
    if not os.path.isdir(target):
        action = "skipped-missing"
        logger.info("[PATH] 工具目录不存在，本次不注入进程 PATH: %s", target)
        return {"action": action, "target": target}

    action = _prepend_process_path(target)
    if action == "present":
        logger.info("[PATH] 当前进程 PATH 已包含工具目录，未做修改: %s", target)
    else:
        logger.info("[PATH] 已把工具目录注入当前进程 PATH（不改注册表）: %s", target)
    return {"action": action, "target": target}


def ensure_tools_on_path_async(target_dir=None) -> None:
    """守护线程里执行 :func:`ensure_tools_on_path`，不拖慢启动、异常不外溢。"""
    import threading  # pylint: disable=import-outside-toplevel

    def _worker():
        try:
            ensure_tools_on_path(target_dir)
        except Exception as exc:  # pylint: disable=broad-except
            logger.info("[PATH] 后台注入进程 PATH 失败（已忽略）: %s", exc)

    threading.Thread(target=_worker, name="path-setup", daemon=True).start()
