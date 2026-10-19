#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""设备 SSH 密码计算引擎（``HPassword.exe`` 的纯 Python 等价实现）。

根据设备 ID 计算 SSH 连接密码，替代对 ``HPassword.exe`` 外部程序的调用。

算法概要：
  1. 初始串 ``s = "HD_" + 设备ID``
  2. 迭代循环（每轮 ``s`` 都推进为 ``md5(s)`` 的小写十六进制，无论字符是否被接受）：
       ``crc = bswap(~CRC32_MSB_first(s, poly=0x4C11DB7))``   # 32 位无符号
       ``r   = signed_mod127(crc)``                            # 32 位有符号除法求余
       ``字符 c = r & 0xFF``
  3. ``r <= 0``（有符号）或 ``c`` 不属于 数字/符号表/小写/大写 之一 → 丢弃该字符
  4. 输出缓冲：前 11 个字符无条件保留；此后只保留"新出现类别"的字符
  5. 当缓冲 >= 11 且 数字/符号/小写/大写 四类齐全 → 输出密码

注：本项目不再调用 ``HPassword.exe``，本模块为其逐字节等价实现。
"""

import hashlib
import struct

# 符号表（HPassword.exe .rdata 中固定字符串: "!@%^*:_.,?"）
SYMBOLS = "!@%^*:_.,?"
# 无条件保留的字符数量（对应 HPassword.exe 栈变量 [esp+0x14] = 11）
LIMIT = 11
# 兜底上限：缓冲达到该长度时强制输出（对应原程序 esi>=127 的强制输出路径）
MAX_BUFFER = 127
# 迭代兜底保护，防止极端输入死循环
MAX_ROUNDS = 10000

MASK32 = 0xFFFFFFFF


def _to_int32(value: int) -> int:
    """将 32 位无符号整数解释为有符号整数。"""
    return value - 0x100000000 if value >= 0x80000000 else value


def _crc32_msb(data: bytes) -> int:
    """CRC-32 非反射（MSB-first）实现，多项式 0x4C11DB7，初值 0xFFFFFFFF。"""
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte << 24
        for _ in range(8):
            if crc & 0x80000000:
                crc = ((crc << 1) ^ 0x4C11DB7) & MASK32
            else:
                crc = (crc << 1) & MASK32
    return crc


def _final_crc(data: bytes) -> int:
    """最终 CRC 值（对应 HPassword.exe 的 ``not ebx; bswap ebx``），返回 32 位无符号。"""
    crc = (~_crc32_msb(data)) & MASK32
    # bswap: 字节序反转（小端存放大端读取）
    return struct.unpack(">I", struct.pack("<I", crc))[0]


def _signed_mod127(ebx: int) -> int:
    """32 位有符号除法求余（对应 HPassword.exe 的魔术数乘法除 127），返回有符号余数。"""
    # imul ebx: edx:eax = (int32)eax * (int32)ebx (64 位有符号乘积)
    product = (_to_int32(0x81020409) * _to_int32(ebx)) & 0xFFFFFFFFFFFFFFFF
    edx = (product >> 32) & MASK32
    # add edx, ebx
    edx = (edx + ebx) & MASK32
    # sar edx, 6（算术右移）
    edx = (_to_int32(edx) >> 6) & MASK32
    eax = edx
    # shr eax, 0x1f
    eax = (eax >> 31) & MASK32
    # add eax, edx
    eax = (eax + edx) & MASK32
    # imul eax, eax, 0x7f
    eax = (_to_int32(eax) * 0x7F) & MASK32
    # sub ebx, eax
    ebx = (ebx - eax) & MASK32
    return _to_int32(ebx)


def _classify(character: int) -> str:
    """字符类别判定，返回 ``digit`` / ``sym`` / ``lower`` / ``upper`` / ``other``。"""
    if 0x30 <= character <= 0x39:
        return "digit"
    if chr(character) in SYMBOLS:
        return "sym"
    if 0x61 <= character <= 0x7A:
        return "lower"
    if 0x41 <= character <= 0x5A:
        return "upper"
    return "other"


def generate_password(device_id: str) -> str:
    """根据设备 ID 计算 SSH 密码（与 ``HPassword.exe`` 输出一致）。

    Args:
        device_id: 设备 ID（如 ``H20-00-A0208``）

    Returns:
        str: 设备密码；设备 ID 为空时返回空字符串
    """
    if not device_id:
        return ""

    state = "HD_" + device_id
    buffer: list = []
    flags = {"digit": False, "sym": False, "lower": False, "upper": False}

    for _ in range(MAX_ROUNDS):
        # 每轮推进状态串（无论字符是否被接受）
        raw = state.encode("ascii", "ignore")
        remainder = _signed_mod127(_final_crc(raw))
        state = hashlib.md5(raw).hexdigest()

        if remainder <= 0:
            continue
        character = remainder & 0xFF
        category = _classify(character)
        if category == "other":
            continue

        if len(buffer) < LIMIT:
            buffer.append(chr(character))
            flags[category] = True
        else:
            if flags[category]:
                continue
            buffer.append(chr(character))
            flags[category] = True

        if len(buffer) >= LIMIT and all(flags.values()):
            break
        if len(buffer) >= MAX_BUFFER:
            break

    return "".join(buffer)
