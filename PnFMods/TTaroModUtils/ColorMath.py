# -*- coding: utf-8 -*-

from Util import logException


CHANNELS = ('a', 'r', 'g', 'b')


def clampByte(v):
    v = int(round(v))
    if v < 0:
        return 0
    if v > 255:
        return 255
    return v


def pack(a, r, g, b):
    return ((clampByte(a) << 24) | (clampByte(r) << 16) |
            (clampByte(g) << 8) | clampByte(b)) & 0xFFFFFFFF


def unpack(packed):
    p = int(packed) & 0xFFFFFFFF
    a = (p >> 24) & 0xFF
    r = (p >> 16) & 0xFF
    g = (p >> 8) & 0xFF
    b = p & 0xFF
    return a, r, g, b


def channelBounds(minInt, maxInt):
    aMin, rMin, gMin, bMin = unpack(minInt if minInt is not None else 0)
    aMax, rMax, gMax, bMax = unpack(maxInt if maxInt is not None else 0xFFFFFFFF)
    return {
        'a': (aMin, aMax),
        'r': (rMin, rMax),
        'g': (gMin, gMax),
        'b': (bMin, bMax),
    }


def clampPerChannel(packed, minInt, maxInt):
    a, r, g, b = unpack(packed)
    bounds = channelBounds(minInt, maxInt)
    a = _clampInto(a, bounds['a'])
    r = _clampInto(r, bounds['r'])
    g = _clampInto(g, bounds['g'])
    b = _clampInto(b, bounds['b'])
    return pack(a, r, g, b)


def _clampInto(v, lohi):
    lo, hi = lohi
    if lo > hi:
        lo, hi = hi, lo
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def isFullRange(minInt, maxInt):
    bounds = channelBounds(minInt, maxInt)
    for ch in CHANNELS:
        lo, hi = bounds[ch]
        if lo != 0 or hi != 255:
            return False
    return True


def toHex(packed):
    return '#{0:08X}'.format(int(packed) & 0xFFFFFFFF)


def rgbToHsv(r, g, b):
    cmax = max(r, g, b)
    cmin = min(r, g, b)
    d = cmax - cmin
    if d == 0:
        h = 0.0
    elif cmax == r:
        h = 60.0 * ((g - b) / float(d))
    elif cmax == g:
        h = 60.0 * ((b - r) / float(d) + 2.0)
    else:
        h = 60.0 * ((r - g) / float(d) + 4.0)
    h = ((h % 360.0) + 360.0) % 360.0
    s = 0.0 if cmax == 0 else 100.0 * d / cmax
    v = 100.0 * cmax / 255.0
    return h, s, v


def hsvToRgb(h, s, v):
    V = v / 100.0
    S = s / 100.0
    out = []
    for n in (5.0, 3.0, 1.0):
        k = (n + h / 60.0) % 6.0
        f = V - V * S * max(0.0, min(min(k, 4.0 - k), 1.0))
        out.append(clampByte(255.0 * f))
    return out[0], out[1], out[2]


def derive(packed, minInt, maxInt):
    try:
        a, r, g, b = unpack(packed)
        bounds = channelBounds(minInt, maxInt)
        full = isFullRange(minInt, maxInt)
        h, s, v = rgbToHsv(r, g, b)
        data = {
            'value': int(packed) & 0xFFFFFFFF,
            'a': a / 255.0, 'r': r / 255.0, 'g': g / 255.0, 'b': b / 255.0,
            'a255': a, 'r255': r, 'g255': g, 'b255': b,
            'vec4': [r / 255.0, g / 255.0, b / 255.0, a / 255.0],
            'hex': toHex(packed),
            'h': h, 's': s, 'v': v,
            'pickerMode': 'hsv' if full else 'rgb',
            'aEditable': bounds['a'][0] != bounds['a'][1],
            'rEditable': bounds['r'][0] != bounds['r'][1],
            'gEditable': bounds['g'][0] != bounds['g'][1],
            'bEditable': bounds['b'][0] != bounds['b'][1],
            'aMin': bounds['a'][0], 'aMax': bounds['a'][1],
            'rMin': bounds['r'][0], 'rMax': bounds['r'][1],
            'gMin': bounds['g'][0], 'gMax': bounds['g'][1],
            'bMin': bounds['b'][0], 'bMax': bounds['b'][1],
        }
        return data
    except Exception as e:
        logException('ColorMath.derive failed for ' + repr(packed), e)
        return {'value': int(packed) & 0xFFFFFFFF}
