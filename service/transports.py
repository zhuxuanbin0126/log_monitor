"""设备命令传输层抽象：协议 exec / ADB / SSH 可替换实现。"""

from abc import ABC, abstractmethod

from service import ssh_service
from service.adb_device_manager import ADBDeviceManager
from service.device_utils import is_android_device
from service.logging_service import get_logger
from service.protocol.command_query import exec_command_triple

logger = get_logger(__name__)


class IDeviceTransport(ABC):
    """远程命令执行接口。"""

    @abstractmethod
    def execute(self, ip: str, password: str, command_script: str,
                base_dir: str = ".") -> tuple:
        """执行远程命令，返回 (stdout, stderr, returncode)。"""


class SshTransport(IDeviceTransport):
    """SSH 传输（Linux 设备的唯一通道）：paramiko 复用连接 → plink 单次回退。

    具体策略见 :mod:`service.ssh_service`：不再有「重试 3 次、每次等 1 秒」的老路，
    也不再要求调用方先跑一次 plink ``echo y`` 去初始化主机密钥。
    """

    def execute(self, ip: str, password: str, command_script: str,
                base_dir: str = ".") -> tuple:
        return ssh_service.execute(ip, password, command_script, base_dir)


class AndroidTransport(IDeviceTransport):
    """Android 传输：**协议加密 exec 优先** → adb → SSH。

    Android 设备不再以 SSH 为首选通道：能通协议时一律走加密 ``Command.exec``
    （既不依赖 SSH，也不依赖先把网络 ADB 连起来，最快且最稳）。
    命令本身返回非 0 退出码时不做通道重试（避免副作用命令被重复执行）。
    """

    def __init__(self, device_id: str):
        self._device_id = device_id
        self._ssh = SshTransport()

    def execute(self, ip: str, password: str, command_script: str,
                base_dir: str = ".") -> tuple:
        # 1) 协议加密 exec（首选）
        triple = exec_command_triple(ip, command_script)
        if triple is not None:
            return triple
        logger.debug("设备 %s 协议 exec 不可用，回落 adb/SSH", self._device_id)

        # 2) 设备已开启网络 ADB → adb
        if ADBDeviceManager.should_use_adb(self._device_id):
            success, serial = ADBDeviceManager.ensure_adb_connected(
                ip, password, self._device_id
            )
            if success and serial:
                return ADBDeviceManager.execute_adb_command(ip, serial, command_script)

        # 3) SSH 兜底
        return self._ssh.execute(ip, password, command_script, base_dir)


def get_transport(device_id: str) -> IDeviceTransport:
    """按设备类型选择传输实现。"""
    if is_android_device(device_id):
        return AndroidTransport(device_id)
    return SshTransport()
