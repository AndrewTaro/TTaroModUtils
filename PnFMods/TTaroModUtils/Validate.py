# -*- coding: utf-8 -*-

import re

import ColorMath
from Util import logException


_RES_KEY_RE = re.compile(r'^\d+x\d+$')


def toBool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, basestring):
        s = value.strip().lower()
        if s in ('1', 'true', 'yes', 'on'):
            return True
        if s in ('0', 'false', 'no', 'off', ''):
            return False
    return bool(value)


def toInt(value):
    if isinstance(value, bool):
        return 1 if value else 0
    return int(round(float(value)))


def toFloat(value):
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    return float(value)


def toStr(value):
    if isinstance(value, basestring):
        return value
    return str(value)


def validate(node, value):
    control = node.get('control')
    default = node.get('default')
    try:
        if control == 'toggle':
            return toBool(value)

        if control == 'color':
            packed = toInt(value)
            return ColorMath.clampPerChannel(
                packed, node.get('min'), node.get('max'))

        if control == 'dropdown':
            return _validateDropdown(node, value, default)

        if control in ('slider', 'number'):
            return _validateNumber(node, value, default)

        if control == 'text':
            return _validateText(node, value, default)

        if control == 'position':
            return validatePosition(value)

        if isinstance(value, (bool, int, float)) or isinstance(value, basestring):
            return value
        return default
    except Exception as e:
        logException('validate failed for ' + str(node.get('key')), e)
        return default


def _validateNumber(node, value, default):
    try:
        num = toFloat(value)
    except Exception:
        return default
    mn = node.get('min')
    mx = node.get('max')
    if mn is not None and num < mn:
        num = mn
    if mx is not None and num > mx:
        num = mx
    step = node.get('step')
    if step:
        try:
            base = mn if mn is not None else 0
            steps = round((num - base) / float(step))
            num = base + steps * float(step)
            if mx is not None and num > mx:
                num = mx
            if mn is not None and num < mn:
                num = mn
        except Exception:
            pass
    decimals = node.get('decimals')
    if decimals is not None:
        num = round(num, int(decimals))
        if int(decimals) == 0:
            num = int(num)
    else:
        if isinstance(default, int) and not isinstance(default, bool) and float(num).is_integer():
            num = int(num)
    return num


def _validateText(node, value, default):
    if not isinstance(value, basestring):
        return default

    if isinstance(value, unicode):
        text = value
    else:
        try:
            text = value.decode('utf-8')
        except Exception:
            return default
    for ch in text:
        if ord(ch) < 0x20 or ord(ch) == 0x7F:
            return default
    maxLength = node.get('maxLength')
    if maxLength is not None:
        try:
            if len(text) > int(maxLength):
                return default
        except Exception:
            pass

    minLength = node.get('minLength')
    if minLength is not None:
        try:
            if len(text) < int(minLength):
                return default
        except Exception:
            pass
    return text


def _validateDropdown(node, value, default):
    options = node.get('options')
    if not isinstance(options, list):
        return value
    allowed = []
    for opt in options:
        if isinstance(opt, dict) and 'value' in opt:
            allowed.append(opt['value'])
    if not allowed:
        return value
    for a in allowed:
        if a == value or _looseEq(a, value):
            return a
    return default if default is not None else allowed[0]


def _looseEq(a, b):
    try:
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return float(a) == float(b)
    except Exception:
        pass
    return False


def validatePosition(value):
    if not isinstance(value, dict):
        return {}
    out = {}
    for resKey, entry in value.items():
        if not isinstance(resKey, basestring) or not _RES_KEY_RE.match(resKey):
            continue
        if not isinstance(entry, dict) or 'x' not in entry or 'y' not in entry:
            continue
        try:

            out[resKey] = {'x': int(round(float(entry['x']))),
                           'y': int(round(float(entry['y'])))}
        except Exception:
            continue
    return out
