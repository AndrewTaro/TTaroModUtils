# -*- coding: utf-8 -*-

import ColorMath
from Util import logInfo, logError, logException


_SENTINEL = object()

_SKIP = object()


def run(flat, storedVersion, migrationFile, legacyReader=None,
        ownedKeys=None, slug='', protected=None):
    ownedKeys = ownedKeys or set()
    migrations = []
    if migrationFile and isinstance(migrationFile.get('migrations'), list):
        migrations = sorted(
            migrationFile['migrations'],
            key=lambda m: m.get('version', 0))

    newVersion = storedVersion


    if storedVersion < 1 and migrations and legacyReader is not None:
        try:
            _importLegacy(flat, migrations, legacyReader, ownedKeys, slug)
        except Exception as e:
            logException('legacy import failed for ' + slug, e)

    for m in migrations:
        version = m.get('version', 0)
        if version <= storedVersion:
            continue
        consumed = set()
        written = set()
        for op in m.get('ops', []):
            try:
                _applyOp(op, flat, ownedKeys, consumed, written, protected)
            except Exception as e:
                logException('migration op failed (%s v%s)' % (slug, version), e)
        for key in consumed - written - (protected or set()):
            if key in flat:
                del flat[key]
        newVersion = version

    return flat, newVersion


def _importLegacy(flat, migrations, legacyReader, ownedKeys, slug):
    legacyKeys = set()
    for m in migrations:
        isFlatToDotted = m.get('version') == 1
        for op in m.get('ops', []):
            if isFlatToDotted:
                frm = op.get('from')
                if frm and frm not in ownedKeys:
                    legacyKeys.add(frm)
            for src in _argSources(op).values():
                if src not in ownedKeys:
                    legacyKeys.add(src)
    imported = 0
    for key in legacyKeys:
        val = legacyReader(key, _SENTINEL)
        if val is _SENTINEL or val is None:
            continue
        flat[key] = val
        imported += 1
    if imported:
        logInfo('legacy import: %s seeded %d key(s)' % (slug, imported))


def _applyOp(op, flat, ownedKeys, consumed=None, written=None, protected=None):
    kind = op.get('op')
    if kind == 'rename':
        _rename(flat, op.get('from'), op.get('to'), ownedKeys)
    elif kind == 'drop':
        _drop(flat, op.get('from'), ownedKeys)
    elif kind == 'transform' and op.get('transform') == 'compose':
        _compose(flat, op, ownedKeys, consumed, written, protected)
    elif kind == 'transform':
        _transform(flat, op, ownedKeys, consumed)
    else:
        logError('unknown migration op (no-op): ' + str(kind))




def _argSources(op):
    out = {}
    args = op.get('args')
    if isinstance(args, dict):
        for name, val in args.items():
            if name.endswith('From') and isinstance(val, basestring) and val:
                out[name] = val
    for i, src in enumerate(_composeSources(op)):
        key = src.get('key') if isinstance(src, dict) else None
        if isinstance(key, basestring) and key:
            out['sources[%d]' % i] = key
    return out


def _rename(flat, frm, to, ownedKeys):
    if not frm or frm in ownedKeys:
        return
    if frm not in flat:
        return
    if to and to in flat:
        del flat[frm]
        return
    if to:
        flat[to] = flat[frm]
    del flat[frm]


def _drop(flat, frm, ownedKeys):
    if frm and frm in flat and frm not in ownedKeys:
        del flat[frm]


def _transform(flat, op, ownedKeys, consumed=None):
    frm = op.get('from')
    to = op.get('to')
    if not frm or frm in ownedKeys:
        return

    sources = _argSources(op)
    present = [k for k in sources.values() if k in flat]
    if not present and frm not in flat:
        return
    value = flat.get(frm)

    name = op.get('transform')
    expr = op.get('expr')
    try:
        if name:
            value = _builtinTransform(name, value, op, flat)
        elif expr:
            value = _evalExpr(expr, value)
    except Exception as e:
        logException('transform %s failed' % name, e)
        return


    if value is _SKIP:
        if to != frm and frm in flat:
            del flat[frm]
        if consumed is not None:
            consumed.update(present if sources else [])
        return

    if to:
        if to == frm or to not in flat:
            flat[to] = value
    if to != frm and frm in flat:
        del flat[frm]

    if consumed is not None:
        consumed.update(present if sources else [])






_MAX_DEPTH = 32
_COMPOSE_FIELDS = frozenset(['op', 'transform', 'to', 'sources', 'value', 'when', 'onExisting'])
_SOURCE_FIELDS = frozenset(['key', 'default', 'consume'])
_ON_EXISTING = frozenset(['keep', 'replace'])
_SHIFTS = (0, 8, 16, 24)
_ARGB_FIELDS = frozenset(['a', 'r', 'g', 'b', 'rgb'])
_EPS = 1e-9

_RESET = object()


class _Stop(Exception):
    pass


def _composeSources(op):
    sources = op.get('sources')
    return sources if isinstance(sources, list) else []


def _isNumber(node):
    return isinstance(node, (int, long, float)) and not isinstance(node, bool)


def _isIndex(node):
    return isinstance(node, (int, long)) and not isinstance(node, bool)


def _num(value):
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, long, float)):
        return float(value)
    logError('compose: non-numeric %r in arithmetic (op skipped)' % (value,))
    raise _Stop()


def _floor(x):
    i = int(x)
    return float(i if i <= x else i - 1)


def _eval(node, ctx):
    if _isNumber(node):
        return node
    for name, arg in node.items():
        return _NODES[name][1](arg, ctx)


def _n(node, ctx):
    return _num(_eval(node, ctx))


def _src(i, ctx):
    flat, sources = ctx
    src = sources[i]
    raw = flat.get(src['key'])
    if raw is not None:
        return raw
    if src.get('default') is None:
        raise _Stop()
    return src['default']


def _present(i, ctx):
    flat, sources = ctx
    return 1.0 if flat.get(sources[i]['key']) is not None else 0.0


def _fold(fn):
    def run(args, ctx):
        out = _n(args[0], ctx)
        for a in args[1:]:
            out = fn(out, _n(a, ctx))
        return out
    return run


def _pair(fn):
    return lambda args, ctx: fn(_n(args[0], ctx), _n(args[1], ctx))


def _div(a, b):
    if b == 0:
        raise _Stop()
    return a / b


def _mod(a, b):
    if b == 0:
        raise _Stop()
    return a % b


def _and(args, ctx):
    for a in args:
        if _n(a, ctx) == 0:
            return 0.0
    return 1.0


def _or(args, ctx):
    for a in args:
        if _n(a, ctx) != 0:
            return 1.0
    return 0.0


def _if(args, ctx):
    return _eval(args[1] if _n(args[0], ctx) != 0 else args[2], ctx)


def _skip(arg, ctx):
    raise _Stop()


def _clamp(args, ctx):
    x, lo, hi = _n(args[0], ctx), _n(args[1], ctx), _n(args[2], ctx)
    return lo if x < lo else (hi if x > hi else x)


def _table(arg, ctx):
    values = arg['values']
    index = int(round(_n(arg['index'], ctx)))
    if 0 <= index < len(values):
        return values[index]
    if 'fallback' in arg:
        return _eval(arg['fallback'], ctx)
    raise _Stop()


def _byte(args, ctx):
    return float((int(_n(args[0], ctx)) >> args[1]) & 0xFF)


def _argb(arg, ctx):
    out = 0
    if 'rgb' in arg:
        out = int(_n(arg['rgb'], ctx)) & 0x00FFFFFF
    for name, shift in (('a', 24), ('r', 16), ('g', 8), ('b', 0)):
        if name in arg:
            byte = int(round(_n(arg[name], ctx)))
            byte = 0 if byte < 0 else (255 if byte > 255 else byte)
            out = (out & ~(0xFF << shift)) | (byte << shift)
    return out


def _b(flag):
    return 1.0 if flag else 0.0



_NODES = {
    'src': ('index', _src),
    'present': ('index', _present),
    'add': ('many', _fold(lambda a, b: a + b)),
    'mul': ('many', _fold(lambda a, b: a * b)),
    'min': ('many', _fold(lambda a, b: a if a <= b else b)),
    'max': ('many', _fold(lambda a, b: a if a >= b else b)),
    'sub': ('pair', _pair(lambda a, b: a - b)),
    'div': ('pair', _pair(_div)),
    'mod': ('pair', _pair(_mod)),
    'abs': ('unary', lambda a, ctx: abs(_n(a, ctx))),

    'round': ('unary', lambda a, ctx: float(round(_n(a, ctx)))),
    'floor': ('unary', lambda a, ctx: _floor(_n(a, ctx))),
    'ceil': ('unary', lambda a, ctx: -_floor(-_n(a, ctx))),
    'clamp': ('triple', _clamp),
    'eq': ('pair', _pair(lambda a, b: _b(abs(a - b) < _EPS))),
    'ne': ('pair', _pair(lambda a, b: _b(abs(a - b) >= _EPS))),
    'lt': ('pair', _pair(lambda a, b: _b(a < b))),
    'le': ('pair', _pair(lambda a, b: _b(a <= b))),
    'gt': ('pair', _pair(lambda a, b: _b(a > b))),
    'ge': ('pair', _pair(lambda a, b: _b(a >= b))),
    'and': ('many', _and),
    'or': ('many', _or),
    'not': ('unary', lambda a, ctx: _b(_n(a, ctx) == 0)),
    'if': ('if', _if),
    'skip': ('none', _skip),
    'reset': ('none', lambda arg, ctx: _RESET),
    'table': ('table', _table),
    'byte': ('byte', _byte),
    'argb': ('argb', _argb),
}

_COUNTS = {'pair': 2, 'triple': 3, 'if': 3, 'byte': 2}


def _treeError(node, nSources, depth, terminal):

    if depth > _MAX_DEPTH:
        return 'tree deeper than %d' % _MAX_DEPTH
    if _isNumber(node):
        return None
    if not isinstance(node, dict) or len(node) != 1:
        return 'node %r is neither a number nor a one-key object' % (node,)
    name, arg = list(node.items())[0]
    spec = _NODES.get(name)
    if spec is None:
        return 'unknown node %r' % (name,)
    shape = spec[0]

    def each(items, term=False):
        for item in items:
            err = _treeError(item, nSources, depth + 1, term)
            if err:
                return err
        return None

    if name == 'reset' and not terminal:
        return '`reset` outside a result position'
    if shape == 'index':
        if not _isIndex(arg) or not 0 <= arg < nSources:
            return '%s index %r out of range (%d sources)' % (name, arg, nSources)
        return None
    if shape == 'none':
        return None if arg is None else '%s takes null' % name
    if shape == 'unary':
        return each([arg])
    if shape in ('many', 'pair', 'triple', 'if', 'byte'):
        if not isinstance(arg, list):
            return '%s takes a list' % name
        want = _COUNTS.get(shape)
        if (want is None and not arg) or (want is not None and len(arg) != want):
            return '%s: wrong argument count %d' % (name, len(arg))
        if shape == 'if':
            return each(arg[:1]) or each(arg[1:], terminal)
        if shape == 'byte':
            if not _isIndex(arg[1]) or arg[1] not in _SHIFTS:
                return 'byte shift %r not in %r' % (arg[1], _SHIFTS)
            return each(arg[:1])
        return each(arg)
    if not isinstance(arg, dict):
        return '%s takes an object' % name
    if shape == 'table':
        if set(arg.keys()) - set(['index', 'values', 'fallback']) or 'index' not in arg:
            return 'table fields %r' % sorted(arg.keys())
        values = arg.get('values')
        if not isinstance(values, list) or not values or not all(_isNumber(v) for v in values):
            return 'table values must be a non-empty list of numbers'
        err = each([arg['index']])
        if err or 'fallback' not in arg:
            return err
        return each([arg['fallback']], terminal)
    if shape == 'argb':
        if not arg or set(arg.keys()) - _ARGB_FIELDS:
            return 'argb fields %r' % sorted(arg.keys())
        return each(arg.values())
    return 'unhandled shape %r' % shape


def composeError(op):

    extra = set(op.keys()) - _COMPOSE_FIELDS
    if extra:
        return 'unknown compose field(s) %r' % sorted(extra)
    to = op.get('to')
    if not isinstance(to, basestring) or not to:
        return '`to` missing'
    sources = op.get('sources')
    if not isinstance(sources, list):
        return '`sources` is not a list'
    for src in sources:
        if not isinstance(src, dict):
            return 'source is not an object'
        extra = set(src.keys()) - _SOURCE_FIELDS
        if extra:
            return 'unknown source field(s) %r' % sorted(extra)
        if not isinstance(src.get('key'), basestring) or not src['key']:
            return 'source `key` missing'
        default = src.get('default')
        if default is not None and not isinstance(default, (bool, int, long, float)):
            return 'source default %r is not a scalar' % (default,)
        if 'consume' in src and not isinstance(src['consume'], bool):
            return 'source `consume` is not a bool'
    if op.get('onExisting', 'keep') not in _ON_EXISTING:
        return 'unknown onExisting %r' % (op.get('onExisting'),)
    if 'value' not in op:
        return '`value` missing'
    err = _treeError(op['value'], len(sources), 0, True)
    if err:
        return 'value: ' + err
    if 'when' in op:
        err = _treeError(op['when'], len(sources), 0, False)
        if err:
            return 'when: ' + err
    return None


def _compose(flat, op, ownedKeys, consumed=None, written=None, protected=None):
    err = composeError(op)
    if err:
        logError('compose op skipped: ' + err)
        return
    sources = op['sources']
    for src in sources:
        if src['key'] in ownedKeys:
            return
    if consumed is not None:
        consumed.update([s['key'] for s in sources
                         if s.get('consume', True) and s['key'] in flat])

    to = op['to']
    ctx = (flat, sources)
    try:
        if 'when' in op and _num(_eval(op['when'], ctx)) == 0:
            return
        value = _eval(op['value'], ctx)
    except _Stop:
        return
    except Exception as e:
        logException('transform compose failed', e)
        return

    if protected and to in protected:
        return
    replace = op.get('onExisting') == 'replace'
    if value is _RESET:
        if replace and to in flat:
            del flat[to]
        return
    if to in flat and not replace:
        return
    flat[to] = value
    if written is not None:
        written.add(to)


def _toNum(value, default=0):
    try:
        return float(value)
    except Exception:
        return default


def _decodeIndex(raw, mn, step):
    return _toNum(mn) + int(round(_toNum(raw))) * _toNum(step, 1)


def _channelByte(flat, args, channel, fallback):
    key = args.get(channel + 'From')
    if not key or key not in flat:
        return fallback
    value = _decodeIndex(flat[key], args.get(channel + 'Min', 0),
                         args.get(channel + 'Step', 1))
    byte = int(round(value * 255))
    return 0 if byte < 0 else (255 if byte > 255 else byte)


def _builtinTransform(name, value, op, flat=None):
    flat = flat if flat is not None else {}
    args = op.get('args') or {}

    if name == 'stepIndex':
        return _decodeIndex(value, args.get('min', 0), args.get('step', 1))

    if name == 'paletteIndex':
        palette = args.get('palette') or []
        hasDefault = args.get('default') is not None
        default = int(args['default']) if hasDefault else 0
        if value is None:

            if not hasDefault:
                return _SKIP
            rgb = default & 0x00FFFFFF
        else:
            index = int(round(_toNum(value)))
            if index < 0 or index >= len(palette):
                index = 0
            rgb = (int(palette[index]) & 0x00FFFFFF) if palette else 0
        alpha = _channelByte(flat, args, 'alpha', (default >> 24) & 0xFF if hasDefault else 255)
        return (alpha << 24) | rgb

    if name == 'packChannels':
        packed = int(args.get('default', 0))
        out = 0
        for channel, shift in (('alpha', 24), ('red', 16),
                               ('green', 8), ('blue', 0)):
            byte = _channelByte(flat, args, channel, (packed >> shift) & 0xFF)
            out |= (byte & 0xFF) << shift
        return out

    if name == 'packRgba':
        if isinstance(value, dict):
            return ColorMath.pack(value.get('a', 255), value.get('r', 0),
                                  value.get('g', 0), value.get('b', 0))
        if isinstance(value, (list, tuple)) and len(value) == 4:
            return ColorMath.pack(value[0], value[1], value[2], value[3])
        return int(value)
    if name == 'unpackRgba':
        a, r, g, b = ColorMath.unpack(int(value))
        return {'a': a, 'r': r, 'g': g, 'b': b}
    if name == 'scale':
        factor = op.get('factor', op.get('args', {}).get('factor', 1))
        return value * factor
    if name == 'cast':
        target = op.get('to_type', op.get('args', {}).get('type', 'float'))
        if target == 'int':
            return int(round(float(value)))
        if target == 'float':
            return float(value)
        if target == 'bool':
            return bool(value)
        if target == 'str':
            return str(value)
        return value
    if name == 'clamp':
        args = op.get('args', op)
        lo = args.get('min')
        hi = args.get('max')
        if lo is not None and value < lo:
            value = lo
        if hi is not None and value > hi:
            value = hi
        return value
    logError('unknown transform (passthrough): ' + str(name))
    return value


def _evalExpr(expr, value):
    raise Exception(
        'migration `expr` ops are not supported. '
        'Re-author as a named `transform` builtin. expr=%r' % (expr,))
