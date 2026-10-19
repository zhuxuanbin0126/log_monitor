"""设备命令传输层抽象：协议 exec / ADB / SSH 可替换实现。"""

import os
from abc import ABC, abstractmethod

from service.adb_device_manager import ADBDeviceManager
from service.device_utils import get_tool_path, is_android_device, run_command
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
    """SSH 传输：优先 paramiko（密码不落命令行），否则回退 plink。"""

    def execute(self, ip: str, password: str, command_script: str,
                base_dir: str = ".") -> tuple:
        try:
            import paramiko  # type: ignore
        except ImportError:
            return self._execute_with_plink(ip, password, command_script, base_dir)

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                ip, username='root', password=password,
                timeout=10, banner_timeout=10, auth_timeout=10,
                look_for_keys=False, allow_agent=False,
            )
            _, stdout, stderr = client.exec_command(command_script, timeout=30)
            out = stdout.read().decode('utf-8', errors='ignore').strip()
            err = stderr.read().decode('utf-8', errors='ignore').strip()
            rc = stdout.channel.recv_exit_status()
            return out, err, rc
        except Exception as e:
            return "", str(e), -1
        finally:
            client.close()

    @staticmethod
    def _execute_with_plink(ip: str, password: str, command_script: str,
                            base_dir: str) -> tuple:
        os.makedirs(base_dir, exist_ok=True)
        script_filename = f"{base_dir}/{ip}temp_script.txt"
        with open(script_filename, 'w', encoding='utf-8') as f:
            f.write(command_script)
            f.write('\nexit\n')

        try:
            plink_exe = get_tool_path('plink.exe')
            cmd = f'{plink_exe} -batch -no-antispoof -l root -pw "{password}" "{ip}" -m {script_filename}'
            return run_command(cmd)
        finally:
            if os.path.exists(script_filename):
                os.remove(script_filename)


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
