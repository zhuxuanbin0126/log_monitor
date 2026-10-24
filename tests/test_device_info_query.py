"""设备信息协议查询单测：Get 一次取 4 键的解析与接线（全离线）。

覆盖字段解析（MAC/设备名/主版本/OTA/Development→ADB 状态）、回环假设备的端到端
一次往返，以及 ToolService 的「Android 协议优先 / Linux 仅取密码」接线。
"""

import json
import socket
import struct
import threading

import pytest

import service.tool_service as ts
import service.protocol.device_info_query as diq
from service.protocol.device_info_query import (
    ADB_STATUS_OFF, ADB_STATUS_ON, ADB_STATUS_UNKNOWN, DEVICE_INFO_KEYS, NA,
    parse_device_info, parse_development, parse_device_name, parse_ethernet_mac,
    parse_mac, parse_ota_version, parse_player_version, query_device_info,
)
from service.protocol.frame import HEADER_SIZE, TYPE_REPLY, build_frame


def _ok_reply(data):
    return {"module": "Get", "reply": {"result": "kSuccess", "data": data}}


# ---------------------------------------------------------------- 纯解析

def test_parse_mac_picks_ethernet_interface():
    network = {"type": "WiFi", "interfaces": [
        {"mac": "11:22:33:44:55:66", "name": "wlan0", "type": "WiFi"},
        {"mac": "AA:BB:CC:DD:EE:FF", "name": "eth0", "type": "Ethernet"},
        {"mac": "77:88:99:AA:BB:CC", "name": "bt", "type": "Bluetooth"},
    ]}
    assert parse_mac(network) == "AA:BB:CC:DD:EE:FF"


def test_parse_mac_without_ethernet_returns_na():
    assert parse_mac({"interfaces": [{"mac": "x", "type": "WiFi"}]}) == NA
    assert parse_mac({"interfaces": []}) == NA
    assert parse_mac(None) == NA
    assert parse_mac({"interfaces": "not-a-list"}) == NA


def test_parse_device_name():
    assert parse_device_name({"deviceName": "  播放器A "}) == "播放器A"
    assert parse_device_name({"deviceId": "X"}) == NA
    assert parse_device_name(None) == NA


def test_parse_player_and_ota_version():
    version = {"app": {"player": "3.0.1.5", "service": "1.0"},
               "system": {"version": "7.1.2", "buildVersion": "V1.2.23.0"}}
    assert parse_player_version(version) == "3.0.1.5"
    assert parse_ota_version(version) == "V1.2.23.0"

    # buildVersion 缺失时回退 system.version
    assert parse_ota_version({"system": {"version": "7.1.2"}}) == "7.1.2"
    assert parse_ota_version({}) == NA
    assert parse_player_version(None) == NA


def test_parse_development_full_combination():
    result = parse_development({"adbMode": "usb,tcp", "adbTimer": 0})
    assert result["adb_status"] == ADB_STATUS_ON        # 网络 ADB（tcp）
    assert result["adb_usb_status"] == ADB_STATUS_ON    # 有线 ADB（usb）
    assert result["adb_detail"] == "tcp+usb/永久"
    assert result["adb_mode"] == "usb,tcp"
    assert result["adb_timer"] == 0


def test_parse_development_tcp_only_and_timed():
    only_tcp = parse_development({"adbMode": "tcp", "adbTimer": 0})
    assert only_tcp["adb_status"] == ADB_STATUS_ON
    assert only_tcp["adb_usb_status"] == ADB_STATUS_OFF
    assert only_tcp["adb_detail"] == "tcp/永久"

    timed = parse_development({"adbMode": "tcp", "adbTimer": 120000})
    assert timed["adb_status"] == ADB_STATUS_ON
    assert timed["adb_timer"] == 120000
    assert "adbTimer=120000" in timed["adb_detail"]


def test_parse_development_usb_only_means_no_network_adb():
    result = parse_development({"adbMode": "usb", "adbTimer": 0})
    assert result["adb_status"] == ADB_STATUS_OFF          # 网络 ADB 未开启
    assert result["adb_usb_status"] == ADB_STATUS_ON       # 有线 ADB 开启
    assert result["adb_detail"] == "usb/永久"


def test_parse_development_missing_or_odd_input():
    assert parse_development(None)["adb_status"] == ADB_STATUS_UNKNOWN
    assert parse_development(None)["adb_usb_status"] == ADB_STATUS_UNKNOWN
    assert parse_development({})["adb_status"] == ADB_STATUS_UNKNOWN

    no_mode = parse_development({"adbTimer": 0})
    assert no_mode["adb_status"] == ADB_STATUS_OFF
    assert no_mode["adb_usb_status"] == ADB_STATUS_OFF
    assert no_mode["adb_detail"] == "未配置adb"

    # timer 为非法字符串时不崩，按「未知」展示
    bad_timer = parse_development({"adbMode": "tcp", "adbTimer": "abc"})
    assert bad_timer["adb_timer"] is None
    assert "adbTimer未知" in bad_timer["adb_detail"]


def test_parse_device_info_maps_all_columns():
    data = {
        "DeviceInfo": {"deviceName": "大厅屏", "deviceId": "H16-00-0001"},
        "VersionInfo": {"app": {"player": "3.0.1.5"},
                        "system": {"buildVersion": "V1.2.23.0"}},
        "NetworkInfo": {"type": "Ethernet", "interfaces": [
            {"mac": "AA:BB:CC:DD:EE:FF", "type": "Ethernet"}]},
        "Development": {"adbMode": "usb,tcp", "adbTimer": 0},
    }
    info = parse_device_info(data)
    assert info["device_name"] == "大厅屏"
    assert info["mac_address"] == "AA:BB:CC:DD:EE:FF"
    assert info["main_version"] == "3.0.1.5"
    assert info["ota_version"] == "V1.2.23.0"
    assert info["system_type"] == "Android"
    assert info["adb_status"] == ADB_STATUS_ON
    assert info["adb_usb_status"] == ADB_STATUS_ON
    assert info["adb_detail"] == "tcp+usb/永久"


# ---------------------------------------------------------------- 回环假设备

def _recv_exact(conn, size):
    buf = b""
    while len(buf) < size:
        chunk = conn.recv(size - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf


class _MockGetDevice:
    """回环 TCP 假设备：读一条 Get 请求，回一条 0x2104 应答帧。"""

    def __init__(self, reply_obj):
        self._reply = reply_obj
        self.received_request = None
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self._sock.settimeout(5.0)
        self.port = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def _serve(self):
        try:
            conn, _ = self._sock.accept()
        except OSError:
            return
        with conn:
            conn.settimeout(5.0)
            conn.sendall(struct.pack("<HH", 4, 0x005F))   # 问候
            _recv_exact(conn, 4)                          # 握手
            head = _recv_exact(conn, 4)
            if len(head) < 4:
                return
            frame_len, _ = struct.unpack("<HH", head)
            body = _recv_exact(conn, frame_len - 4)
            self.received_request = json.loads(body[HEADER_SIZE - 4:].decode("utf-8"))
            conn.sendall(build_frame(self._reply, TYPE_REPLY))

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_exc):
        self._thread.join(timeout=6.0)
        self._sock.close()
        return False


def test_query_device_info_single_roundtrip_with_four_keys():
    reply = _ok_reply({
        "DeviceInfo": {"deviceName": "门口屏", "deviceId": "A3L-0001"},
        "VersionInfo": {"app": {"player": "2.8.0.9"},
                        "system": {"version": "7.1.2", "buildVersion": "V1.1.0.0"}},
        "NetworkInfo": {"interfaces": [{"mac": "0A:0B:0C:0D:0E:0F", "type": "Ethernet"}]},
        "Development": {"adbMode": "usb,tcp", "adbTimer": 0},
    })
    with _MockGetDevice(reply) as server:
        info = query_device_info("127.0.0.1", port=server.port,
                                 connect_timeout=3.0, recv_timeout=2.0)

    assert info is not None
    assert info["device_name"] == "门口屏"
    assert info["mac_address"] == "0A:0B:0C:0D:0E:0F"
    assert info["main_version"] == "2.8.0.9"
    assert info["ota_version"] == "V1.1.0.0"
    assert info["adb_status"] == ADB_STATUS_ON
    # 一次往返即取全部 4 键
    assert server.received_request["module"] == "Get"
    assert server.received_request["ask"] == {"list": DEVICE_INFO_KEYS}


def test_query_device_info_returns_none_when_unreachable():
    assert query_device_info("127.0.0.1", port=1, connect_timeout=0.3,
                             recv_timeout=0.3) is None


def test_query_device_info_returns_none_on_non_success():
    reply = {"module": "Get", "reply": {"result": "kNotImplemented"}}
    with _MockGetDevice(reply) as server:
        assert query_device_info("127.0.0.1", port=server.port,
                                 connect_timeout=3.0, recv_timeout=2.0) is None


# ---------------------------------------------------------------- MAC 回退（旧固件）

def test_parse_ethernet_mac():
    assert parse_ethernet_mac({"mac": "88:a6:00:0a:92:10"}) == "88:a6:00:0a:92:10"
    assert parse_ethernet_mac({"dhcp": True}) == NA
    assert parse_ethernet_mac(None) == NA


def test_parse_device_info_uses_ethernet_fallback():
    data = {"NetworkInfo": {"interfaces": [{"mac": "x", "type": "WiFi"}]},
            "DeviceInfo": {"deviceName": "旧固件设备"}}
    info = parse_device_info(data, ethernet={"mac": "88:A6:00:0A:92:10"})
    assert info["device_name"] == "旧固件设备"
    assert info["mac_address"] == "88:A6:00:0A:92:10"


def test_query_device_info_falls_back_to_ethernet_get(monkeypatch):
    """NetworkInfo 无以太网 mac 时，按需补查一次 Get ["Ethernet"] 取 mac。"""
    calls = []

    def fake_query_keys(_host, keys, **_kw):
        calls.append(list(keys))
        if keys == ["Ethernet"]:
            return {"module": "Get", "reply": {"result": "kSuccess", "data": {
                "Ethernet": {"dhcp": True, "ip": "192.168.80.216",
                             "mac": "88:a6:00:0a:92:10", "mask": "255.255.254.0"}}}}
        return {"module": "Get", "reply": {"result": "kSuccess", "data": {
            "NetworkInfo": {"interfaces": [{"mac": "x", "type": "WiFi"}]},
            "VersionInfo": {"app": {"player": "2.12.9.7"}},
            "DeviceInfo": {"deviceName": "A6L"}}}}

    monkeypatch.setattr(diq, "query_keys", fake_query_keys)
    info = diq.query_device_info("192.168.80.216")

    assert info["mac_address"] == "88:a6:00:0a:92:10"
    assert info["main_version"] == "2.12.9.7"
    assert calls == [DEVICE_INFO_KEYS, ["Ethernet"]]


def test_query_device_info_no_extra_get_when_mac_present(monkeypatch):
    calls = []

    def fake_query_keys(_host, keys, **_kw):
        calls.append(list(keys))
        return {"module": "Get", "reply": {"result": "kSuccess", "data": {
            "NetworkInfo": {"interfaces": [{"mac": "AA:BB", "type": "Ethernet"}]}}}}

    monkeypatch.setattr(diq, "query_keys", fake_query_keys)
    info = diq.query_device_info("192.168.80.216")

    assert info["mac_address"] == "AA:BB"
    assert calls == [DEVICE_INFO_KEYS]      # 只一次往返，不补查


# ---------------------------------------------------------------- ToolService 接线

def test_build_device_info_linux_only_password(monkeypatch):
    """Linux 机型：只取密码 + 版本（主版本来自 SSH 版本文件，OTA 恒为 N/A）。"""
    monkeypatch.setattr(ts, 'query_linux_version', lambda _ip, _pw: '7.11.34.0')
    info = ts.ToolService._build_device_info('D16-00-0001', '192.168.1.9', 'pwd')
    assert info['system_type'] == 'Linux'
    assert info['adb_status'] == '不支持'
    assert info['adb_usb_status'] == '不支持'
    assert info['mac_address'] == NA
    assert info['device_name'] == NA
    assert info['ota_version'] == NA          # Linux 无 OTA 版本
    assert info['main_version'] == '7.11.34.0'


def test_build_device_info_linux_version_unreachable(monkeypatch):
    """Linux 机型取不到版本时退回 N/A，不抛异常。"""
    monkeypatch.setattr(ts, 'query_linux_version', lambda _ip, _pw: NA)
    info = ts.ToolService._build_device_info('D16-00-0001', '192.168.1.9', 'pwd')
    assert info['main_version'] == NA
    assert info['ota_version'] == NA


def test_get_version_info_linux_skips_ota_query(monkeypatch):
    """Linux 分支不再跑 Android 专用的 getprop/dumpsys，只读版本文件。"""
    calls = []
    monkeypatch.setattr(ts, 'query_linux_version',
                        lambda ip, pw: calls.append((ip, pw)) or '7.10.62.3')
    monkeypatch.setattr(
        ts.ToolService, 'run_command',
        staticmethod(lambda *a, **k: pytest.fail('Linux 不应走 adb/命令通道')))

    ota_version, main_version = ts.ToolService.get_version_info(
        'C16L-D24-0F308', '192.168.81.127', 'pwd')

    assert ota_version == NA                 # 无 OTA 版本 → 固定 N/A
    assert main_version == '7.10.62.3'
    assert calls == [('192.168.81.127', 'pwd')]


def test_build_device_info_android_prefers_protocol(monkeypatch):
    monkeypatch.setattr(ts, 'query_device_info', lambda _ip, **_kw: {
        'mac_address': 'AA:BB:CC:DD:EE:FF', 'device_name': '大厅屏',
        'system_type': 'Android', 'ota_version': 'V1.2.23.0',
        'main_version': '3.0.1.5', 'adb_status': '开启',
        'adb_detail': 'usb+tcp/永久', 'adb_mode': 'usb,tcp', 'adb_timer': 0,
    })
    info = ts.ToolService._build_device_info('H16-00-0001', '192.168.1.8', 'pwd')
    assert info['mac_address'] == 'AA:BB:CC:DD:EE:FF'
    assert info['main_version'] == '3.0.1.5'
    assert info['ota_version'] == 'V1.2.23.0'
    assert info['adb_status'] == '开启'


def test_build_device_info_android_falls_back_when_protocol_unavailable(monkeypatch):
    monkeypatch.setattr(ts, 'query_device_info', lambda _ip, **_kw: None)
    monkeypatch.setattr(
        ts.ADBDeviceManager, 'ensure_adb_connected',
        staticmethod(lambda ip, pw, dev: (True, 'serial-1')))
    monkeypatch.setattr(
        ts.ToolService, 'get_advanced_device_info',
        staticmethod(lambda d, i, p: ('MAC-FALLBACK', 'NAME', 'Android')))
    monkeypatch.setattr(
        ts.ToolService, 'get_version_info',
        staticmethod(lambda d, i, p: ('OTA-FB', 'MAIN-FB')))

    info = ts.ToolService._build_device_info('H16-00-0001', '192.168.1.8', 'pwd')
    assert info['mac_address'] == 'MAC-FALLBACK'
    assert info['device_name'] == 'NAME'
    assert info['ota_version'] == 'OTA-FB'
    assert info['main_version'] == 'MAIN-FB'
    assert info['adb_status'] == '开启'


def test_build_device_info_list_path_does_not_force_adb(monkeypatch):
    """get_device_list 的回落路径不应主动去连 adb（用缓存状态）。"""
    monkeypatch.setattr(ts, 'query_device_info', lambda _ip, **_kw: None)
    monkeypatch.setattr(ts.ADBDeviceManager, 'get_cached_status',
                        staticmethod(lambda _dev: '未开启'))
    monkeypatch.setattr(
        ts.ADBDeviceManager, 'ensure_adb_connected',
        staticmethod(lambda *a, **k: pytest.fail('不应调用 ensure_adb_connected')))
    monkeypatch.setattr(
        ts.ToolService, 'get_advanced_device_info',
        staticmethod(lambda d, i, p: ('MAC', 'NAME', 'Android')))
    monkeypatch.setattr(
        ts.ToolService, 'get_version_info',
        staticmethod(lambda d, i, p: ('OTA', 'MAIN')))

    info = ts.ToolService._build_device_info('H16-00-0001', '192.168.1.8', 'pwd',
                                             enable_adb_fallback=False)
    assert info['adb_status'] == '未开启'
    assert info['adb_usb_status'] == '未知'      # 回落通道判断不了有线 ADB
