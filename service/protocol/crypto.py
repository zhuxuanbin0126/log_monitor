#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""MagicPlayer 加密消息密码学层（AES-128-CBC / PKCS7）。

设备侧真值源（``DataUtils`` / ``TcpMsgClient.handleSwapSlatAsk`` / ``HashUtils``）：
  - ``TRANSFORMATION = "AES/CBC/PKCS7Padding"``，``IV_PARAM = "1234567890000000"``
  - ``remoteSlat / localSlat = hex(PC 盐) / hex(设备盐)``
  - ``key = MD5("HUIDUSDK" + remoteSlat + localSlat)``（16 字节，AES-128）

本模块只做「算法复刻」，不持有任何网络/会话状态。
"""

import hashlib
from typing import Optional

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# 与设备侧 DataUtils.IV_PARAM 完全一致（16 字节 ASCII）
AES_IV = b"1234567890000000"
# 与设备侧 TcpMsgClient.handleSwapSlatAsk 的拼接前缀完全一致
KEY_PREFIX = "HUIDUSDK"

BLOCK_SIZE = 16
"""AES 分组长度"""

SALT_SIZE = 16
"""交换盐值长度（字节，AES-128 密钥长度）"""


def to_hex(raw: bytes) -> str:
    """字节 → 小写 hex（等价设备侧 HashUtils.toHexString）。"""
    return raw.hex()


def derive_key(pc_salt: bytes, device_salt: bytes) -> bytes:
    """密钥派生：``MD5("HUIDUSDK" + PC盐hex + 设备盐hex)`` → 16 字节。

    两个盐均为**原始 16 字节**，内部各自 hex 成 32 位小写字符串后拼接。
    """
    origin = KEY_PREFIX + to_hex(pc_salt) + to_hex(device_salt)
    return hashlib.md5(origin.encode("utf-8")).digest()


def pkcs7_pad(data: bytes, block: int = BLOCK_SIZE) -> bytes:
    """PKCS7 填充。"""
    pad = block - (len(data) % block)
    return data + bytes([pad]) * pad


def pkcs7_unpad(data: bytes, block: int = BLOCK_SIZE) -> bytes:
    """PKCS7 去填充；非法时抛 ValueError。"""
    if not data or len(data) % block != 0:
        raise ValueError("密文长度非法")
    pad = data[-1]
    if pad < 1 or pad > block or data[-pad:] != bytes([pad]) * pad:
        raise ValueError("PKCS7 填充非法")
    return data[:-pad]


def _new_cipher(key: bytes) -> Cipher:
    """按 IV = AES_IV 构造 AES-CBC 密码对象。"""
    return Cipher(algorithms.AES(key), modes.CBC(AES_IV))


def encrypt_aes(data: bytes, key: bytes) -> bytes:
    """AES-128-CBC + PKCS7 加密（IV 固定）。"""
    encryptor = _new_cipher(key).encryptor()
    return encryptor.update(pkcs7_pad(data)) + encryptor.finalize()


def decrypt_aes(data: bytes, key: bytes) -> Optional[bytes]:
    """AES-128-CBC + PKCS7 解密；失败返回 None（对齐设备侧语义）。"""
    if len(data) % BLOCK_SIZE != 0:
        return None
    try:
        decryptor = _new_cipher(key).decryptor()
        return pkcs7_unpad(decryptor.update(data) + decryptor.finalize())
    except Exception:  # pylint: disable=broad-except
        return None
