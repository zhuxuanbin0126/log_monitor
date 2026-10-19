"""设备命令传输层抽象：ADB / SSH 可替换实现。"""

import os
from abc import ABC, abstractmethod

from service.adb_device_manager import ADBDeviceManager
from service.device_utils import get_tool_path, is_android_device, run_command


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
    """Android 传输：ADB 可用时走 adb，否则回退 SSH。"""

    def __init__(self, device_id: str):
        self._device_id = device_id
        self._ssh = SshTransport()

    def execute(self, ip: str, password: str, command_script: str,
                base_dir: str = ".") -> tuple:
        if ADBDeviceManager.should_use_adb(self._device_id):
            success, serial = ADBDeviceManager.ensure_adb_connected(
                ip, password, self._device_id
            )
            if success and serial:
                return ADBDeviceManager.execute_adb_command(ip, serial, command_script)
        return self._ssh.execute(ip, password, command_script, base_dir)


def get_transport(device_id: str) -> IDeviceTransport:
    """按设备类型选择传输实现。"""
    if is_android_device(device_id):
        return AndroidTransport(device_id)
    return SshTransport()
