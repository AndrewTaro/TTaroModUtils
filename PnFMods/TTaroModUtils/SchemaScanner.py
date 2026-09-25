# -*- coding: utf-8 -*-

import Util
_u1 = Util._u1
from Util import logInfo, logError, logException
import Migrations


SCHEMA_SUFFIX = '.schema.json'
_OWNED_BACKEND = 'minimapOption'
MIN_SCHEMA_VERSION = 4

_AUTHOR_CHARS = 'abcdefghijklmnopqrstuvwxyz'
_AUTHOR_DIGITS = '0123456789'
_RESERVED_AUTHORS = frozenset([
    'registry', 'installedMods', 'framework', 'uiState', 'dragState'])

MAX_OP_VOCABULARY = 3
_KNOWN_OPS = frozenset(['rename', 'drop', 'transform'])
_KNOWN_TRANSFORMS = frozenset([
    'stepIndex', 'paletteIndex', 'packChannels', 'packRgba', 'unpackRgba',
    'scale', 'cast', 'clamp', 'compose'])


def isNative(node):
    return node.get('backend') == _OWNED_BACKEND or node.get('owned') is False


def scan():
    index = SchemaIndex()
    directory = Util.schemasDir()
    logInfo('scanning schemas in ' + str(directory))

    names = [n for n in Util.listDir(directory) if n.endswith(SCHEMA_SUFFIX)]
    accepted = []
    byId = {}
    for name in sorted(names):
        path = _u1.path.join(directory, name)
        data = Util.readJson(path)
        if not _validSchema(data, name):
            continue
        accepted.append((name, data))
        byId.setdefault(data['id'], []).append(name)

    duplicated = set()
    for modId in sorted(byId.keys()):
        if len(byId[modId]) > 1:
            duplicated.add(modId)
            logError('duplicate mod id %r in %s -- refusing all of them; delete the stale '
                     'file (a rename leaves the old one behind)'
                     % (modId, ', '.join(sorted(byId[modId]))))

    for name, data in accepted:
        if data['id'] in duplicated:
            continue
        try:
            index._addMod(data)
        except Exception as e:
            logException('failed to index ' + name, e)

    index._loadShared(directory)
    index._finalize()
    logInfo('indexed %d mod(s)' % len(index._order))
    return index


def _validSchema(data, name):
    if not isinstance(data, dict):
        logError('skip %s: not an object' % name)
        return False
    for field in ('schemaVersion', 'id', 'author', 'modName', 'slug', 'tree'):
        if field not in data:
            logError('skip %s: missing %s' % (name, field))
            return False
    ver = data.get('schemaVersion')
    if not isinstance(ver, int) or ver < MIN_SCHEMA_VERSION:
        logError('skip %s: schemaVersion %r < %d (rebuild from CMS)' % (name, ver, MIN_SCHEMA_VERSION))
        return False
    if not isinstance(data.get('tree'), list):
        logError('skip %s: tree is not a list' % name)
        return False
    if not _validAuthor(data.get('author'), name):
        return False
    modId = data.get('id')
    if not isinstance(modId, basestring) or not modId or _hasPathChars(modId):
        logError('skip %s: id %r is not a plain identifier' % (name, modId))
        return False
    slug = data.get('slug')
    if not isinstance(slug, basestring) or not slug or '.' in slug:
        logError('skip %s: slug %r is missing or contains a dot' % (name, slug))
        return False
    return True


def _validAuthor(author, name):
    if not isinstance(author, basestring) or not author:
        logError('skip %s: author %r is not a string' % (name, author))
        return False
    if author[0] not in _AUTHOR_CHARS:
        logError('skip %s: author %r must start with a lowercase letter' % (name, author))
        return False
    for ch in author:
        if ch not in _AUTHOR_CHARS and ch not in _AUTHOR_DIGITS:
            logError('skip %s: author %r must be lowercase alphanumeric' % (name, author))
            return False
    if author in _RESERVED_AUTHORS:
        logError('skip %s: author %r is a reserved DataHub name' % (name, author))
        return False
    return True


def _hasPathChars(text):
    for ch in ('/', '\\', ':', '..'):
        if ch in text:
            return True
    return False


def _validMigrations(data, name):
    if data is None:
        return True
    if not isinstance(data, dict):
        logError('migrations %s: not an object -- refusing' % name)
        return False

    ver = data.get('opVocabularyVersion', 1)
    if not isinstance(ver, int) or isinstance(ver, bool):
        logError('migrations %s: opVocabularyVersion %r is not an int -- refusing'
                 % (name, ver))
        return False
    if ver > MAX_OP_VOCABULARY:
        logError('migrations %s: opVocabularyVersion %d > %d -- refusing; '
                 'update TTaroModUtils' % (name, ver, MAX_OP_VOCABULARY))
        return False

    migrations = data.get('migrations')
    if migrations is None:
        return True
    if not isinstance(migrations, list):
        logError('migrations %s: `migrations` is not a list -- refusing' % name)
        return False

    for m in migrations:
        if not isinstance(m, dict):
            logError('migrations %s: migration entry is not an object -- refusing' % name)
            return False
        for op in (m.get('ops') or []):
            if not isinstance(op, dict):
                logError('migrations %s: op is not an object -- refusing' % name)
                return False
            kind = op.get('op')
            if kind not in _KNOWN_OPS:
                logError('migrations %s: unknown op %r -- refusing' % (name, kind))
                return False
            if 'expr' in op:
                logError('migrations %s: `expr` op is not supported -- refusing '
                         '(re-author as a named transform)' % name)
                return False
            if kind == 'transform':
                if op.get('transform') not in _KNOWN_TRANSFORMS:
                    logError('migrations %s: unknown transform %r -- refusing'
                             % (name, op.get('transform')))
                    return False
            if op.get('transform') == 'compose':
                err = Migrations.composeError(op)
                if err:
                    logError('migrations %s: compose op to %r: %s -- refusing'
                             % (name, op.get('to'), err))
                    return False
            elif 'when' in op:

                logError('migrations %s: `when` on %r -- refusing'
                         % (name, op.get('transform') or kind))
                return False
    return True


class SchemaIndex(object):

    def __init__(self):
        self._mods = {}
        self._order = []
        self._reverse = {}
        self._owner = {}
        self._bare = {}
        self._groupKeys = set()
        self._installed = set()
        self._frameworkSlug = None
        self._constants = {}


    def _addMod(self, data):
        author = data['author']
        slug = data['slug']
        modAddr = author + '.' + slug
        record = {
            'modName': data.get('modName', slug),
            'slug': slug,
            'author': author,
            'modAddr': modAddr,
            'storeId': data['id'],
            'order': data.get('order', 0),
            'framework': bool(data.get('framework', False)),
            'tree': data.get('tree', []),
            'nodes': {},
            'defaults': {},
            'keySet': set(),
            'ownedKeys': set(),
            'positionKeys': set(),
            'conditions': {},
            'groupConditions': {},
            'migrationFile': None,
        }
        self._walk(data.get('tree', []), record)
        self._mods[modAddr] = record
        if record['framework']:
            self._frameworkSlug = modAddr
        else:
            self._installed.add(modAddr)

    def _hub(self, record, key):
        return record['author'] + '.' + key

    def _walk(self, nodes, record):
        for node in nodes:
            if not isinstance(node, dict):
                continue
            kind = node.get('kind')
            if kind == 'setting':
                self._indexSetting(node, record)
            elif kind == 'group':
                self._indexGroup(node, record)
            children = node.get('children')
            if isinstance(children, list):
                self._walk(children, record)

    def _indexGroup(self, node, record):
        gkey = node.get('key')
        if not gkey:
            return
        cond = node.get('enabledWhen')
        if isinstance(cond, dict) and cond.get('conditions'):
            hkey = self._hub(record, gkey)
            record['groupConditions'][hkey] = cond
            self._groupKeys.add(hkey)
            self._registerDeps(record, hkey, cond)

    def _indexSetting(self, node, record):
        control = node.get('control')
        key = node.get('key')
        slug = record['modAddr']

        if isNative(node):
            if key:
                record['ownedKeys'].add(key)
                record['nodes'][key] = node
            return

        if control == 'button' or not key:
            return

        record['nodes'][key] = node
        record['keySet'].add(key)
        hkey = self._hub(record, key)
        self._owner[hkey] = slug
        self._bare[hkey] = key
        if control == 'position':
            record['defaults'][key] = node.get('defaultPosition', node.get('default'))
            record['positionKeys'].add(key)
        else:
            record['defaults'][key] = node.get('default')

        cond = node.get('enabledWhen')
        if isinstance(cond, dict) and cond.get('conditions'):
            record['conditions'][hkey] = cond
            self._registerDeps(record, hkey, cond)

    def _registerDeps(self, record, hubDependentKey, conditions):
        for depKey in _conditionKeys(conditions):
            self._reverse.setdefault(self._hub(record, depKey), []).append(
                (record['modAddr'], hubDependentKey))


    def _loadShared(self, directory):
        const = Util.readJson(_u1.path.join(directory, 'Data', 'constants.json'))
        if isinstance(const, dict):
            self._constants = const.get('constants', {}) or {}
        else:
            logError('constants.json missing or invalid')

    def _finalize(self):
        self._order = sorted(
            self._mods.keys(),
            key=lambda s: (self._mods[s]['order'], s))
        for slug in self._order:
            mf = Util.readJson(self._migrationPath(slug))
            refused = not _validMigrations(mf, slug)
            self._mods[slug]['migrationFile'] = None if refused else mf
            self._mods[slug]['migrationRefused'] = refused
        self._warnPrefixCollisions()

    def _warnPrefixCollisions(self):
        found = []
        for slug in self._order:
            record = self._mods[slug]
            stored = record['keySet']
            positions = record['positionKeys']
            for pkey in sorted(stored):
                clashes = sorted(k for k in stored
                                 if k != pkey and k.startswith(pkey + '.'))
                if clashes:
                    found.append((slug, pkey, clashes))
                    kind = 'position key' if pkey in positions else 'key'
                    logError(
                        'schema %s: %s %r is a PREFIX of stored key(s) %s'
                        ' -- they share one node in ModPrefs/%s.json and will'
                        ' overwrite each other; rename it CMS-side'
                        % (slug, kind, pkey, ', '.join(clashes), record['storeId']))
        return found

    def _migrationPath(self, modAddr):
        record = self._mods[modAddr]
        return _u1.path.join(Util.schemasDir(), 'Migrations',
                            record['author'] + '-' + record['slug'] + '.migrations.json')


    def slugs(self):
        return list(self._order)

    def displaySlugs(self):
        return [s for s in self._order if s != self._frameworkSlug]

    def frameworkSlug(self):
        return self._frameworkSlug

    def isFramework(self, slug):
        return self._mods.get(slug, {}).get('framework', False)

    def modName(self, slug):
        return self._mods.get(slug, {}).get('modName', slug)

    def tree(self, slug):
        return self._mods.get(slug, {}).get('tree', [])

    def node(self, slug, fullKey):
        return self._mods.get(slug, {}).get('nodes', {}).get(fullKey)

    def keySet(self, slug):
        return self._mods.get(slug, {}).get('keySet', set())

    def ownerSlug(self, hubKey):
        return self._owner.get(hubKey)

    def bareKey(self, hubKey):
        return self._bare.get(hubKey)

    def resolve(self, hubKey):
        mod = self._owner.get(hubKey)
        if mod is None:
            return None, None
        return mod, self._bare.get(hubKey)

    def hubKey(self, modAddr, storeKey):
        record = self._mods.get(modAddr)
        if record is None:
            return storeKey
        return record['author'] + '.' + storeKey

    def storeId(self, modAddr):
        return self._mods.get(modAddr, {}).get('storeId')

    def author(self, modAddr):
        return self._mods.get(modAddr, {}).get('author')

    def positionKeys(self, slug):
        return self._mods.get(slug, {}).get('positionKeys', set())

    def legacyOwnedFromKeys(self, slug):
        return self._mods.get(slug, {}).get('ownedKeys', set())

    def migrationFile(self, slug):
        return self._mods.get(slug, {}).get('migrationFile')

    def migrationRefused(self, slug):
        return bool(self._mods.get(slug, {}).get('migrationRefused'))

    def legacyPositions(self, slug):
        mf = self._mods.get(slug, {}).get('migrationFile')
        if isinstance(mf, dict):
            lp = mf.get('legacyPositions')
            if isinstance(lp, list):
                return lp
        return []

    def defaultFor(self, slug, fullKey):
        return self._mods.get(slug, {}).get('defaults', {}).get(fullKey)

    def conditionsFor(self, slug, fullKey):
        return self._mods.get(slug, {}).get('conditions', {}).get(fullKey)

    def dependents(self, depKey):
        return self._reverse.get(depKey, [])

    def installedMods(self):
        return set(self._installed)

    def isInstalled(self, slug):
        return slug in self._installed

    def constants(self):
        return self._constants

    def allConditionEntries(self):
        out = []
        for slug in self._order:
            conds = self._mods[slug]['conditions']
            for fullKey, cond in conds.items():
                out.append((slug, fullKey, cond))
        return out

    def isGroupKey(self, key):
        return key in self._groupKeys

    def groupConditionsFor(self, slug, groupKey):
        return self._mods.get(slug, {}).get('groupConditions', {}).get(groupKey)

    def allGroupConditionEntries(self):
        out = []
        for slug in self._order:
            for groupKey, cond in self._mods[slug]['groupConditions'].items():
                out.append((slug, groupKey, cond))
        return out


def _conditionKeys(condition):
    keys = []
    if not isinstance(condition, dict):
        return keys
    kind = condition.get('kind')
    if kind == 'compare' and condition.get('key'):
        keys.append(condition['key'])
    elif kind == 'group':
        for sub in condition.get('conditions', []) or []:
            keys.extend(_conditionKeys(sub))
    return keys
