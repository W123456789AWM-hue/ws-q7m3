"""Ed25519 数字签名（RFC 8032），纯 Python，不依赖任何第三方库。

用途：在线更新的版本清单 latest.json 由云端用私钥签名，程序里只有公钥，用来验证清单确实是我们发的，
防止下载地址被劫持后推送恶意安装包。验证一次约几十毫秒，足够用。
"""
from __future__ import annotations

import hashlib

_p = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_d = -121665 * pow(121666, _p - 2, _p) % _p
_I = pow(2, (_p - 1) // 4, _p)


def _inv(x: int) -> int:
    return pow(x, _p - 2, _p)


def _recover_x(y: int, sign: int) -> int | None:
    x2 = (y * y - 1) * _inv(_d * y * y + 1) % _p
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_p + 3) // 8, _p)
    if (x * x - x2) % _p:
        x = x * _I % _p
    if (x * x - x2) % _p:
        return None
    if (x & 1) != sign:
        x = _p - x
    return x


_By = 4 * _inv(5) % _p
_Bx = _recover_x(_By, 0)
_B = (_Bx, _By, 1, _Bx * _By % _p)        # 扩展坐标 (X, Y, Z, T)
_ZERO = (0, 1, 1, 0)


def _add(P, Q):
    X1, Y1, Z1, T1 = P
    X2, Y2, Z2, T2 = Q
    A = (Y1 - X1) * (Y2 - X2) % _p
    B = (Y1 + X1) * (Y2 + X2) % _p
    C = T1 * 2 * _d * T2 % _p
    D = Z1 * 2 * Z2 % _p
    E, F, G, H = B - A, D - C, D + C, B + A
    return E * F % _p, G * H % _p, F * G % _p, E * H % _p


def _mul(s: int, P):
    Q = _ZERO
    while s > 0:
        if s & 1:
            Q = _add(Q, P)
        P = _add(P, P)
        s >>= 1
    return Q


def _encode(P) -> bytes:
    X, Y, Z, _ = P
    zi = _inv(Z)
    x, y = X * zi % _p, Y * zi % _p
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decode(s: bytes):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign, y = y >> 255, y & ((1 << 255) - 1)
    if y >= _p:
        return None
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % _p)


def _equal(P, Q) -> bool:
    return (P[0] * Q[2] - Q[0] * P[2]) % _p == 0 and (P[1] * Q[2] - Q[1] * P[2]) % _p == 0


def _h(m: bytes) -> int:
    return int.from_bytes(hashlib.sha512(m).digest(), "little")


def _expand(seed: bytes) -> tuple[int, bytes]:
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def public_key(seed: bytes) -> bytes:
    """32 字节私钥（种子）→ 32 字节公钥"""
    a, _ = _expand(seed)
    return _encode(_mul(a, _B))


def sign(seed: bytes, msg: bytes) -> bytes:
    a, prefix = _expand(seed)
    A = _encode(_mul(a, _B))
    r = _h(prefix + msg) % _L
    R = _encode(_mul(r, _B))
    s = (r + _h(R + A + msg) * a) % _L
    return R + int.to_bytes(s, 32, "little")


def verify(pub: bytes, msg: bytes, sig: bytes) -> bool:
    if len(sig) != 64:
        return False
    A, R = _decode(pub), _decode(sig[:32])
    if A is None or R is None:
        return False
    s = int.from_bytes(sig[32:], "little")
    if s >= _L:
        return False
    k = _h(sig[:32] + pub + msg) % _L
    return _equal(_mul(s, _B), _add(R, _mul(k, A)))
