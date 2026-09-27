# -*- coding: utf-8 -*-

import Util
_u1 = Util._u1
from Util import logInfo, logError, logException

_MIGRATION_FIELD = '__migrationVersion'


_PENDING_FIELD = '__pendingEdits'

_RESERVED_OPAQUE = frozenset(['ttModConfig.__uiState'])


class PrefsStore(object):

    def __init__(self, schemaIndex, legacyReader=None, saveMode='auto',
                 legacyReaderFor=None):
        self._index = schemaIndex
        self._legacyReader = legacyReader
        self._legacyReaderFor = legacyReaderFor
        self._saveMode = saveMode
        self._flat = {}
        self._version = {}
        self._locked = {}
        self._fresh = set()
        self._dirty = set()
        self._dir = Util.prefsDir()
        self._writer = _DeferredWriter(self._dir)


    def loadAll(self):
        Util.ensureDir(self._dir)
        self._cleanupOrphanTmp()
        self._locked = {}
        for slug in self._index.slugs():
            try:
                self._loadMod(slug)
            except Exception as e:
                logException('load failed for ' + slug, e)
                self._lock(slug, 'loadError')



    def _lock(self, slug, reason):
        logError('%s LOCKED (%s): settings read as defaults and are not saved' % (slug, reason))
        self._locked[slug] = reason
        self._flat[slug] = {}
        self._version[slug] = 0
        self._dirty.discard(slug)
        self._fresh.discard(slug)
        self._writer.discard(self._fileId(slug))

    def isLocked(self, slug):
        return slug in self._locked


    def lockReason(self, slug):
        return self._locked.get(slug)

    def _lockReason(self, slug, version):
        target = self._index.migrationTarget(slug)
        status = self._index.migrationStatus(slug)
        if target is None:
            return status
        if version > target:
            return 'ahead'
        if version == target:
            return None
        if status != 'ok':
            return status
        versions = self._index.migrationVersions(slug)
        for v in range(version + 1, target + 1):
            if v not in versions:
                return 'gap'
        return None


    def _readStore(self, path):
        unreadable = False
        for p in (path, path + '.bak'):
            if not Util.isFile(p):
                continue
            raw = Util.readJson(p)
            if isinstance(raw, dict):
                return raw, False
            unreadable = True
        return None, unreadable

    def _loadMod(self, slug):
        import Migrations

        raw, unreadable = self._readStore(self._path(slug))
        if unreadable:
            return self._lock(slug, 'storeCorrupt')
        flat = {}
        version = 0
        pending = set()
        if raw is not None:
            version = raw.get(_MIGRATION_FIELD, 0) or 0
            if not _isCount(version):
                return self._lock(slug, 'storeCorrupt')
            stored = raw.get(_PENDING_FIELD)
            if isinstance(stored, list):
                pending = set(k for k in stored if isinstance(k, basestring))
            nested = raw.get('prefs', {})
            if isinstance(nested, dict):
                opaque = Migrations.positionSources(
                    self._index.migrationFile(slug), version,
                    self._index.positionKeys(slug), self._index.migrationTarget(slug))
                if slug == self._index.frameworkSlug():
                    opaque = opaque | _RESERVED_OPAQUE
                flat = Util.flattenWithLeaves(nested, opaque)
        reason = self._lockReason(slug, version)
        if reason:
            return self._lock(slug, reason)


        if not raw:
            self._fresh.add(slug)

        reader = self._legacyReader
        if self._legacyReaderFor is not None:
            override = self._legacyReaderFor(slug)
            if override is not None:
                reader = override

        ownedKeys = self._index.legacyOwnedFromKeys(slug)
        flat, newVersion = Migrations.run(
            flat, version, self._index.migrationFile(slug),
            legacyReader=reader, ownedKeys=ownedKeys, slug=slug, protected=pending,
            target=self._index.migrationTarget(slug))

        changed = (newVersion != version) or bool(pending)
        changed = self._pruneOrphans(slug, flat) or changed
        changed = self._coerceLoaded(slug, flat) or changed

        self._flat[slug] = flat
        self._version[slug] = newVersion
        if changed:
            self._dirty.add(slug)
            self.flush(slug)

    def _pruneOrphans(self, slug, flat):
        known = self._index.keySet(slug)
        orphans = [k for k in flat.keys()
                   if k not in known and not _isReserved(k)]
        for k in orphans:
            del flat[k]
        if orphans:
            logInfo('pruned %d orphan key(s) from %s' % (len(orphans), slug))
        return bool(orphans)

    def _coerceLoaded(self, slug, flat):
        import Validate

        changed = False
        for fullKey in list(flat.keys()):
            if _isReserved(fullKey):
                continue
            node = self._index.node(slug, fullKey)
            if node is None:
                continue
            value = flat[fullKey]
            try:
                cast = Validate.validate(node, value)
            except Exception as e:
                logException('load cast failed for %s %s' % (slug, fullKey), e)
                continue
            if _sameTyped(cast, value):
                continue
            logInfo('cast on load: %s %s %r -> %r' % (slug, fullKey, value, cast))
            flat[fullKey] = cast
            changed = True
        return changed


    def get(self, slug, fullKey, default=None):
        return self._flat.get(slug, {}).get(fullKey, default)

    def getEffective(self, slug, fullKey):
        flat = self._flat.get(slug, {})
        if fullKey in flat:
            return flat[fullKey]
        return self._index.defaultFor(slug, fullKey)

    def allEffective(self, slug):
        out = {}
        for fullKey in self._index.keySet(slug):
            out[fullKey] = self.getEffective(slug, fullKey)
        return out

    def version(self, slug):
        return self._version.get(slug, 0)

    def wasFresh(self, slug):
        return slug in self._fresh


    def set(self, slug, fullKey, value):
        if slug in self._locked:
            return
        flat = self._flat.setdefault(slug, {})
        default = self._index.defaultFor(slug, fullKey)
        if _equal(value, default):
            if fullKey in flat:
                del flat[fullKey]
        else:
            flat[fullKey] = value
        self._dirty.add(slug)

    def setReserved(self, slug, fullKey, value):
        if slug in self._locked:
            return
        flat = self._flat.setdefault(slug, {})
        flat[fullKey] = value
        self._dirty.add(slug)

    def setIndex(self, schemaIndex):
        self._index = schemaIndex

    def remove(self, slug, fullKey):
        if slug in self._locked:
            return
        flat = self._flat.get(slug, {})
        if fullKey in flat:
            del flat[fullKey]
            self._dirty.add(slug)

    def resetAll(self, slug):
        if slug in self._locked:
            return
        self._flat[slug] = {}
        self._dirty.add(slug)

    def writePosition(self, slug, fullKey, resKey, x, y):
        if slug in self._locked:
            return
        flat = self._flat.setdefault(slug, {})
        posMap = flat.get(fullKey)
        if not isinstance(posMap, dict):
            posMap = {}
        posMap = dict(posMap)
        posMap[resKey] = {'x': int(round(float(x))), 'y': int(round(float(y)))}
        flat[fullKey] = posMap
        self._dirty.add(slug)

    def removePositionBucket(self, slug, fullKey, resKey):
        if not resKey or slug in self._locked:
            return False
        flat = self._flat.get(slug, {})
        posMap = flat.get(fullKey)
        if not isinstance(posMap, dict) or resKey not in posMap:
            return False
        posMap = dict(posMap)
        del posMap[resKey]
        if posMap:
            flat[fullKey] = posMap
        elif fullKey in flat:
            del flat[fullKey]
        self._dirty.add(slug)
        return True

    def readPosition(self, slug, fullKey, resKey):
        posMap = self._flat.get(slug, {}).get(fullKey)
        if isinstance(posMap, dict):
            entry = posMap.get(resKey)
            if isinstance(entry, dict) and 'x' in entry and 'y' in entry:
                return entry
        return None


    def isDirty(self, slug):
        return slug in self._dirty

    def flush(self, slug):
        if slug not in self._flat or slug in self._locked:
            return
        snapshot = self._serialize(slug)
        self._writer.enqueue(self._fileId(slug), snapshot)
        self._dirty.discard(slug)

    def flushAll(self):
        for slug in list(self._dirty):
            self.flush(slug)

    def _serialize(self, slug):
        nested = Util.nest(self._flat.get(slug, {}))
        return {
            _MIGRATION_FIELD: self._version.get(slug, 0),
            'prefs': nested,
        }

    def shutdown(self):
        self.flushAll()
        self._writer.shutdown()


    def _fileId(self, slug):
        fileId = self._index.storeId(slug)
        if not fileId:
            logError('no store id for %s -- schema was indexed without one' % (slug,))
            return slug
        return fileId

    def _path(self, slug):
        return _u1.path.join(self._dir, self._fileId(slug) + '.json')

    def _cleanupOrphanTmp(self):
        for name in Util.listDir(self._dir):
            if name.endswith('.tmp'):
                try:
                    _u1.remove(_u1.path.join(self._dir, name))
                except Exception:
                    pass


def _isCount(v):
    return isinstance(v, (int, long)) and not isinstance(v, bool) and v >= 0


def _isReserved(fullKey):
    return fullKey.rsplit('.', 1)[-1].startswith('__')


def _equal(a, b):
    if isinstance(a, float) or isinstance(b, float):
        try:
            return abs(float(a) - float(b)) < 1e-9
        except Exception:
            return a == b
    return a == b


def _storedType(value):
    if isinstance(value, bool):
        return bool
    if isinstance(value, (int, long)):
        return int
    return type(value)


def _sameTyped(a, b):
    if _storedType(a) is not _storedType(b):
        return False
    if isinstance(a, dict):
        if len(a) != len(b):
            return False
        for k in a:
            if k not in b or not _sameTyped(a[k], b[k]):
                return False
        return True
    if isinstance(a, list):
        if len(a) != len(b):
            return False
        for i in range(len(a)):
            if not _sameTyped(a[i], b[i]):
                return False
        return True
    return a == b


class _DeferredWriter(object):

    _DELAY = 0.5

    def __init__(self, directory):
        self._dir = directory
        self._pending = {}
        self._handle = None

    def enqueue(self, fileId, snapshot):
        self._pending[fileId] = snapshot
        if self._handle is None:
            try:
                self._handle = callbacks.callback(self._DELAY, self._onTimer)
            except Exception as e:
                logException('deferred writer schedule failed, writing sync', e)
                self._drain()

    def discard(self, fileId):
        self._pending.pop(fileId, None)

    def _onTimer(self):
        if self._handle is not None:
            try:
                callbacks.cancel(self._handle)
            except Exception:
                pass
        self._handle = None
        self._drain()

    def _drain(self):
        pending = self._pending
        self._pending = {}
        for fileId, snapshot in pending.items():
            try:
                _writeAtomic(self._dir, fileId, snapshot)
            except Exception as e:
                logException('deferred write', e)

    def shutdown(self):
        if self._handle is not None:
            try:
                callbacks.cancel(self._handle)
            except Exception:
                pass
            self._handle = None
        self._drain()


def _writeAtomic(directory, fileId, snapshot):
    final = _u1.path.join(directory, fileId + '.json')
    tmp = final + '.tmp'
    bak = final + '.bak'
    text = Util.jsonEncode(snapshot)
    if isinstance(text, unicode):
        text = text.encode('utf-8')
    flags = _u1.O_WRONLY | _u1.O_CREAT | _u1.O_TRUNC | getattr(_u1, 'O_BINARY', 0)
    fd = _u1.open(tmp, flags)
    try:
        _u1.write(fd, text)
        try:
            _u1.fsync(fd)
        except Exception:
            pass
    finally:
        _u1.close(fd)
    if _u1.path.isfile(final):
        try:
            if _u1.path.isfile(bak):
                _u1.remove(bak)
            _u1.rename(final, bak)
        except Exception:
            pass
    _renameWithRetry(tmp, final)


def _renameWithRetry(src, dst, attempts=5):
    import time
    last = None
    for i in range(attempts):
        try:
            _u1.rename(src, dst)
            return
        except Exception as e:
            last = e
            time.sleep(0.02 * (i + 1))
    raise last
