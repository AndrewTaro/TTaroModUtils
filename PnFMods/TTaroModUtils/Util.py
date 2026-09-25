# -*- coding: utf-8 -*-

API_VERSION = 'API_v1.0'
MOD_NAME = 'TTaroModUtils'


from Codec import _u1, _u6, _u7, _u8, _u9, _u10, _u11


def logInfo(*args):
    msg = '[{0}] {1}'.format(MOD_NAME, ', '.join(str(a) for a in args))
    utils.logInfo(msg)


def logError(*args):
    msg = '[{0}] ERROR {1}'.format(MOD_NAME, ', '.join(str(a) for a in args))
    utils.logError(msg)


def logException(prefix, exc):
    logError(prefix, repr(exc))


def jsonDecode(text):
    return utils.jsonDecode(text)


def jsonEncode(obj):
    return utils.jsonEncode(obj)


def readFile(path):
    try:
        fd = _u1.open(path, _u1.O_RDONLY | getattr(_u1, 'O_BINARY', 0))
    except Exception:
        return None
    try:
        parts = []
        while True:
            chunk = _u1.read(fd, 65536)
            if not chunk:
                break
            parts.append(chunk)
        return ''.join(parts)
    except Exception:
        return None
    finally:
        try:
            _u1.close(fd)
        except Exception:
            pass


def readJson(path):
    text = readFile(path)
    if text is None:
        return None
    try:
        return jsonDecode(text)
    except Exception as e:
        logException('readJson failed for ' + str(path), e)
        return None


def isFile(path):
    try:
        return _u1.path.isfile(path)
    except Exception:
        return False


def listDir(path):
    try:
        return _u1.listdir(path)
    except Exception:
        return []





def getModDir():
    try:
        return utils.getModDir()
    except Exception:
        return ''


def _normSlashes(path):
    return path.replace('\\', '/')


def gameRootDir():
    mod = _normSlashes(getModDir())
    marker = '/res_mods/'
    idx = mod.lower().find(marker)
    if idx != -1:
        resmods = mod[:idx + len(marker)]
        root = _u1.path.abspath(_u1.path.join(resmods, '..', '..', '..'))
        return root
    return _u1.path.abspath(_u1.path.join(mod, '..', '..', '..', '..'))


def schemasDir():
    mod = getModDir()
    return _u1.path.abspath(_u1.path.join(mod, '..', '..', 'ModSchemas'))


def prefsDir():
    d = _u1.path.join(gameRootDir(), 'ModPrefs')
    return d


def stageSize():
    try:
        entity = dataHub.getSingleEntity('stage')
        if not entity:
            return None
        comp = entity[constants.UiComponents.stage]
        w = comp.width
        h = comp.height
        if w is None or h is None:
            return None
        return (float(w), float(h))
    except Exception as e:
        logException('stage size unavailable', e)
        return None


def resKey():
    size = stageSize()
    if size is None:
        return None
    return '%dx%d' % (int(round(size[0])), int(round(size[1])))


def chatBoxSection():
    try:
        entity = dataHub.getSingleEntity('userPrefs')
        if not entity:
            return {}
        prefs = entity[constants.UiComponents.userPrefs].userPrefs
        section = prefs.get('chatBoxWidth', {})
        return section if isinstance(section, dict) else {}
    except Exception as e:
        logException('chatBoxWidth section unavailable', e)
        return {}


def ensureDir(path):
    try:
        if not _u1.path.isdir(path):
            _u1.makedirs(path)
        return True
    except Exception as e:
        logException('ensureDir failed for ' + str(path), e)
        return False


def splitKey(dottedKey):
    return dottedKey.split('.')


def joinKey(parts):
    return '.'.join(parts)


def getNested(nested, dottedKey, default=None):
    cur = nested
    for part in splitKey(dottedKey):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def hasNested(nested, dottedKey):
    sentinel = object()
    return getNested(nested, dottedKey, sentinel) is not sentinel


def setNested(nested, dottedKey, value):
    setNestedPath(nested, splitKey(dottedKey), value)


def setNestedPath(nested, parts, value):
    if not parts:
        return
    cur = nested
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def delNested(nested, dottedKey):
    parts = splitKey(dottedKey)
    stack = []
    cur = nested
    for part in parts[:-1]:
        if not isinstance(cur, dict) or part not in cur:
            return False
        stack.append((cur, part))
        cur = cur[part]
    if not isinstance(cur, dict) or parts[-1] not in cur:
        return False
    del cur[parts[-1]]
    for parent, part in reversed(stack):
        child = parent.get(part)
        if isinstance(child, dict) and not child:
            del parent[part]
        else:
            break
    return True


def flatten(nested, _prefix='', _out=None):
    if _out is None:
        _out = {}
    for k, v in nested.items():
        key = k if not _prefix else _prefix + '.' + k
        if isinstance(v, dict) and v:
            flatten(v, key, _out)
        else:
            _out[key] = v
    return _out


def flattenWithLeaves(nested, opaqueKeys, _prefix='', _out=None):
    if _out is None:
        _out = {}
    for k, v in nested.items():
        key = k if not _prefix else _prefix + '.' + k
        if key in opaqueKeys:
            _out[key] = v
        elif isinstance(v, dict) and v:
            flattenWithLeaves(v, opaqueKeys, key, _out)
        else:
            _out[key] = v
    return _out


def nest(flat):
    out = {}
    for key, value in flat.items():
        setNested(out, key, value)
    return out
