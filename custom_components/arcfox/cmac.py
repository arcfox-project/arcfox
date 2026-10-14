"""AES-CMAC helpers matching the ARCFOX SDK's ``AceMacUtil``.

The app signs the JSON-serialized ``BctpControlCmdEntity`` with AES-CMAC
(RFC 4493). The key is the per-vehicle ``rcKey`` hex string and the digest is
returned as uppercase hex.
"""

from __future__ import annotations

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_BLOCK = 16
_RB = 0x87


def _xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def _shift_left_one(data: bytes) -> bytes:
    carry = 0
    out = bytearray(_BLOCK)
    for i in range(_BLOCK - 1, -1, -1):
        out[i] = ((data[i] << 1) & 0xFF) | carry
        carry = 1 if (data[i] & 0x80) else 0
    return bytes(out)


def _aes_ecb_encrypt(key: bytes, block: bytes) -> bytes:
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return encryptor.update(block) + encryptor.finalize()


def cmac(key: bytes, message: bytes) -> bytes:
    """Return the AES-CMAC tag for ``message`` under ``key``."""
    if len(key) not in (16, 24, 32):
        raise ValueError("AES key must be 16, 24 or 32 bytes")

    l_block = _aes_ecb_encrypt(key, bytes(_BLOCK))

    k1 = _shift_left_one(l_block)
    if l_block[0] & 0x80:
        k1 = _xor(k1, bytes(_BLOCK - 1) + bytes([_RB]))

    k2 = _shift_left_one(k1)
    if k1[0] & 0x80:
        k2 = _xor(k2, bytes(_BLOCK - 1) + bytes([_RB]))

    complete_blocks = len(message) // _BLOCK
    last_complete = complete_blocks * _BLOCK

    if len(message) % _BLOCK == 0 and len(message) > 0:
        last = _xor(message[last_complete - _BLOCK :], k1)
        padded = message[: last_complete - _BLOCK]
    else:
        pad = bytes([0x80]) + bytes(_BLOCK - 1 - (len(message) % _BLOCK))
        last = _xor(message[last_complete:] + pad, k2)
        padded = message[:last_complete]

    state = bytes(_BLOCK)
    for i in range(0, len(padded), _BLOCK):
        state = _aes_ecb_encrypt(key, _xor(state, padded[i : i + _BLOCK]))
    return _aes_ecb_encrypt(key, _xor(state, last))


def cmac_hex(key: bytes, message: bytes) -> str:
    """Return the uppercase hex CMAC digest."""
    return cmac(key, message).hex().upper()


def cmac_string(key_hex: str, message: str) -> str | None:
    """Match ``AceMacUtil.calculateCMACString(keyHex, message)``."""
    try:
        key = bytes.fromhex(key_hex)
    except ValueError:
        return None
    if len(key) not in (16, 24, 32):
        return None
    return cmac_hex(key, message.encode("utf-8"))
