# -*- coding: utf-8 -*-

from Util import logException


def evaluate(condition, valueOf, installedMods):
    if not condition:
        return True
    try:
        return _one(condition, valueOf, installedMods)
    except Exception as e:
        logException('condition eval failed', e)
        return True


def _one(cond, valueOf, installedMods):
    if not isinstance(cond, dict):
        return True
    kind = cond.get('kind')
    if kind == 'compare':
        return _compare(cond, valueOf)
    if kind == 'installed':
        mod = cond.get('mod')
        return (mod is None) or (mod in installedMods)
    if kind == 'group':
        return _group(cond, valueOf, installedMods)
    return True


def _group(cond, valueOf, installedMods):
    join = cond.get('join', 'all')
    subs = cond.get('conditions', [])
    if not subs:
        return True
    if join == 'any':
        return any(_one(s, valueOf, installedMods) for s in subs)
    return all(_one(s, valueOf, installedMods) for s in subs)


def _compare(cond, valueOf):
    key = cond.get('key')
    op = cond.get('op')
    values = cond.get('values', [])
    if key is None:
        return True
    actual = valueOf(key)

    if op == 'in':
        return any(_eq(actual, v) for v in values)
    if op == 'eq':
        return values and _eq(actual, values[0])
    if op == 'neq':
        return not (values and _eq(actual, values[0]))

    if not values:
        return True
    target = values[0]
    try:
        a = float(actual)
        b = float(target)
    except Exception:
        return True
    if op == 'gt':
        return a > b
    if op == 'gte':
        return a >= b
    if op == 'lt':
        return a < b
    if op == 'lte':
        return a <= b
    return True


def _eq(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    try:
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return abs(float(a) - float(b)) < 1e-9
    except Exception:
        pass
    return a == b
