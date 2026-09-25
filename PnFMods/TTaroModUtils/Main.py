# -*- coding: utf-8 -*-

API_VERSION = 'API_v1.0'
MOD_NAME = 'TTaroModUtils'

import Util
_u1 = Util._u1

import ColorMath
import Validate
import Conditions
import SchemaScanner
from PrefsStore import PrefsStore
from DataHub import (DataHub, componentKey, REGISTRY_KEY,
                     INSTALLED_KEY, FRAMEWORK_KEY, UISTATE_KEY, DRAGSTATE_KEY)
from EventHandlers import EventHandlers
from CursorHold import CursorHold
from Util import logInfo, logError, logException


FRAMEWORK_SLUG = 'ttaro.ttaro-mod-config'
_FRAMEWORK_JSON = '_framework.json'

SAVE_MODE_KEY = 'ttModConfig.saveMode'
HOT_RELOAD_KEY = 'ttModConfig.hotReloadEnabled'
UISTATE_STORE_KEY = 'ttModConfig.__uiState'
SELECTED_TAB_PATH = 'selectedTab'
SELECTED_PAGE_PATH = 'selectedPage'

ROOT_PAGE_LABEL = 'IDS_TT_TITLE_GENERAL'

_DISPLAY_FROM_AGGREGATE = {'inline': 'transparent', 'tooltip': 'popup'}


def _isPage(node):
    return node.get('kind') == 'group' and node.get('display') == 'section'


def _pagesFor(tree):


    pages = []
    loose = []
    for i, node in enumerate(tree):
        if not isinstance(node, dict) or _isPage(node):
            continue
        kind = node.get('kind')
        if (kind == 'setting' and not node.get('hidden')) or (kind == 'group' and node.get('hasVisible')):
            loose.append(i)
    if loose:
        pages.append({'value': 0, 'label': ROOT_PAGE_LABEL, 'idx': loose})
    for i, node in enumerate(tree):
        if not isinstance(node, dict) or not _isPage(node):
            continue
        if not node.get('hasVisible'):
            continue
        pages.append({'value': len(pages),
                      'label': node.get('label') or '',
                      'idx': [i]})
    return pages


def _hasVisibleLeaf(group):


    for child in group.get('children') or []:
        if not isinstance(child, dict):
            continue
        if child.get('kind') == 'setting':
            if not child.get('hidden'):
                return True
        elif child.get('hasVisible'):
            return True
    return False

_FRAMEWORK_BOOTSTRAP = (
    ('saveMode', SAVE_MODE_KEY),
    ('hotReloadEnabled', HOT_RELOAD_KEY),
)

_FRAMEWORK_DEFAULTS = {
    'saveMode': 'auto',
    'hotReloadEnabled': False,
}

_SENTINEL = object()
_DEBOUNCE_SECONDS = 0.5


class Framework(object):

    def __init__(self):
        self._settings = _loadFrameworkSettings()
        self._index = None
        self._store = None
        self._dh = DataHub()
        self._handlers = None
        self._chatBoxReader = None
        self._flushScheduled = False
        self._flushTimer = None
        self._foldTimer = None
        self._retryTimer = None
        self._started = False
        self._uiState = {}
        self._geom = {}
        self._posPublished = {}
        self._pageCounts = {}
        self._cursor = CursorHold()


    def start(self):
        if self._started:
            return
        self._started = True
        try:
            self._index = SchemaScanner.scan()
            self._chatBoxReader = _makeLegacyReader()
            self._store = PrefsStore(
                self._index,
                legacyReader=self._chatBoxReader,
                legacyReaderFor=_makeLegacyReaderFor(self._chatBoxReader),
                saveMode=self._settings['saveMode'])
            self._store.loadAll()
            self._uiState = self._loadUiState()

            self._subscribeLifecycle()

            self._handlers = EventHandlers(self)
            if not self._handlers.register():
                self._scheduleHandlerRetry()

            self._publishShared()
            self._createSettingComponents()
            self._initialVisibilityPass()
            self._createGroupComponents()
            self._foldLegacyPositions()
            self._warnOrphanLegacyPositions()
            self._registerDragInput()

            logInfo('framework ready (saveMode=%s, hotReload=%s, '
                    '%d mods, framework-row=%s)'
                    % (self._settings['saveMode'],
                       self._settings['hotReloadEnabled'],
                       len(self._index.displaySlugs()),
                       self._index.frameworkSlug() is not None))
        except Exception as e:
            logException('framework start failed', e)

    def _cancelTimer(self, name):
        handle = getattr(self, name, None)
        if handle is not None:
            try:
                callbacks.cancel(handle)
            except Exception:
                pass
        setattr(self, name, None)

    def _scheduleHandlerRetry(self, attempt=1):
        if attempt > 5:
            return

        def retry():
            self._cancelTimer('_retryTimer')
            if self._handlers.register():
                logInfo('write-path handlers registered on retry %d' % attempt)
            else:
                self._scheduleHandlerRetry(attempt + 1)
        try:
            self._retryTimer = callbacks.callback(1.0, retry)
        except Exception:
            pass


    def _publishShared(self):
        mods = []
        for slug in self._index.displaySlugs():
            tree = self._publishTree(slug)
            pages = _pagesFor(tree)

            self._pageCounts[slug] = len(pages)
            mods.append({
                'slug': slug,
                'modName': self._index.modName(slug),
                'tree': tree,
                'pages': pages,
            })
        self._dh.create(REGISTRY_KEY, {'mods': mods})
        self._dh.create(INSTALLED_KEY,
                        {'mods': sorted(self._index.installedMods())})
        self._dh.create(UISTATE_KEY, self._uiStateData())
        self._dh.create(DRAGSTATE_KEY, {'isDragging': False, 'isSnapMode': False})
        if self._index.frameworkSlug() is not None:
            self._dh.create(FRAMEWORK_KEY, self._buildFrameworkData())


    def _buildFrameworkData(self):
        fwSlug = self._index.frameworkSlug()
        tree = self._publishTree(fwSlug)
        return {
            'slug': fwSlug,
            'modName': self._index.modName(fwSlug),
            'tree': tree,
            'pages': _pagesFor(tree),
        }


    def _publishTree(self, slug):
        return self._qualifyNodes(self._index.tree(slug), self._index.author(slug))

    def _qualifyNodes(self, nodes, author):
        out = []
        for node in nodes:
            if not isinstance(node, dict):
                out.append(node)
                continue
            copied = {}
            for name in node:
                copied[name] = node[name]
            key = copied.get('key')

            if author and isinstance(key, basestring) and key and not SchemaScanner.isNative(copied):
                copied['key'] = author + '.' + key
            children = copied.get('children')
            if isinstance(children, list):
                copied['children'] = self._qualifyNodes(children, author)


            if copied.get('kind') == 'group':
                copied['hasVisible'] = _hasVisibleLeaf(copied)

                if not copied.get('display'):
                    copied['display'] = _DISPLAY_FROM_AGGREGATE.get(copied.get('aggregate'), 'section')
            out.append(copied)
        return out


    def _updateFrameworkComponent(self):
        if self._index.frameworkSlug() is not None:
            self._dh.update(FRAMEWORK_KEY, self._buildFrameworkData())


    def _loadUiState(self):
        fwSlug = self._index.frameworkSlug()
        if fwSlug is None:
            return {}
        blob = self._store.get(fwSlug, UISTATE_STORE_KEY, None)
        return blob if isinstance(blob, dict) else {}

    def _uiStateData(self):
        slugs = self._index.displaySlugs()
        tab = self._uiState.get('selectedTab', '')
        if tab not in slugs:
            tab = slugs[0] if slugs else ''



        tabIndex = slugs.index(tab) if slugs else 0
        return {
            'selectedTab': tab,
            'selectedTabIndex': tabIndex,
            'collapsed': self._uiState.get('collapsed', {}),
            'selectedPage': self._clampedPages(),
        }



    def _clampedPages(self):
        stored = self._uiState.get(SELECTED_PAGE_PATH, {})
        if not isinstance(stored, dict):
            stored = {}

        cleaned = {}
        for key in stored:
            value = stored[key]
            if isinstance(value, (int, long)) and not isinstance(value, bool) and value >= 0:
                cleaned[key] = value
        if cleaned != stored:
            self._uiState[SELECTED_PAGE_PATH] = cleaned
            stored = cleaned
        out = {}
        for slug in self._index.displaySlugs():
            value = stored.get(slug, 0)
            if not isinstance(value, (int, long)) or isinstance(value, bool) or value < 0:
                value = 0
            count = self._pageCounts.get(slug)
            if count is not None and count > 0 and value >= count:
                value = count - 1
            out[slug] = value
        return out

    def setUiState(self, path, value):
        fwSlug = self._index.frameworkSlug()
        if fwSlug is None or not path:
            return
        if isinstance(path, (list, tuple)):
            parts = [p for p in path if p != '']
            if not parts:
                return
            Util.setNestedPath(self._uiState, parts, value)
        else:
            Util.setNested(self._uiState, path, value)
        self._store.setReserved(fwSlug, UISTATE_STORE_KEY, self._uiState)
        self._dh.update(UISTATE_KEY, self._uiStateData())
        self._scheduleFlush(fwSlug)

    def setCursorHold(self, want):
        if self._cursor is None:
            return
        try:
            self._cursor.request(want)
        except Exception as e:
            logException('setCursorHold', e)
            try:
                self._cursor.releaseNow()
            except Exception:
                pass

    def getSelectedTab(self):
        return self._uiState.get(SELECTED_TAB_PATH, '') or ''

    def _createSettingComponents(self):
        installed = self._index.installedMods()
        for slug in self._index.slugs():
            for storeKey in self._index.keySet(slug):
                value = self._store.getEffective(slug, storeKey)
                hubKey = self._hk(slug, storeKey)
                data = self._buildData(slug, hubKey, value, installed)
                self._dh.create(componentKey(hubKey), data)

    def _initialVisibilityPass(self):
        installed = self._index.installedMods()
        for slug, fullKey, conds in self._index.allConditionEntries():
            visible = Conditions.evaluate(
                conds, self._valueOf(slug), installed)
            key = componentKey(fullKey)
            if self._dh.has(key):
                value = self._store.getEffective(slug, self._sk(fullKey))
                data = self._buildData(slug, fullKey, value, installed, visible)
                self._dh.update(key, data)

    def _createGroupComponents(self):
        installed = self._index.installedMods()
        for slug, groupKey, conds in self._index.allGroupConditionEntries():
            visible = Conditions.evaluate(
                conds, self._valueOf(slug), installed)
            self._dh.create(componentKey(groupKey), {'visible': visible})


    def _buildData(self, slug, fullKey, value, installed, visible=None):
        node = self._index.node(slug, self._sk(fullKey)) or {}
        if visible is None:
            conds = self._index.conditionsFor(slug, fullKey)
            visible = Conditions.evaluate(conds, self._valueOf(slug), installed)
        if node.get('control') == 'color':
            data = ColorMath.derive(value, node.get('min'), node.get('max'))
        elif node.get('control') == 'position':
            data = {'value': self._resolvePositionFor(slug, fullKey)}
        else:
            data = {'value': value}
        data['visible'] = visible
        return data

    def _resolvePosition(self, mapValue):
        key = Util.resKey()
        if key and isinstance(mapValue, dict):
            b = mapValue.get(key)
            if isinstance(b, dict) and 'x' in b and 'y' in b:
                return {'x': b['x'], 'y': b['y']}
        return None

    _POS_ANCHORS_X = ('left', 'center', 'right')
    _POS_ANCHORS_Y = ('top', 'middle', 'bottom')

    def _resolvePositionFor(self, slug, fullKey):
        storeKey = self._sk(fullKey)
        xy = self._resolvePosition(self._store.get(slug, storeKey, None))
        if xy is None:
            xy = self._resolveDefaultPosition(
                fullKey, self._index.defaultFor(slug, storeKey))
        return self._clampOnScreen(fullKey, xy)

    def _resolveDefaultPosition(self, fullKey, spec):
        if not isinstance(spec, dict):
            return None
        stage = Util.stageSize()
        if stage is None:
            return None
        g = self._geom.get(fullKey) or {}
        ax = self._resolveAxis(spec.get('x'), stage[0], self._POS_ANCHORS_X,
                               g.get('w', 0.0), g.get('pox', 0.0))
        ay = self._resolveAxis(spec.get('y'), stage[1], self._POS_ANCHORS_Y,
                               g.get('h', 0.0), g.get('poy', 0.0))
        if ax is None or ay is None:
            return None
        return {'x': int(round(ax)), 'y': int(round(ay))}

    @staticmethod
    def _resolveAxis(axis, extent, anchors, size, pivotOff):
        if not isinstance(axis, dict):
            return None
        try:
            offset = float(axis.get('offset'))
        except Exception:
            return None
        anchor = axis.get('anchor')
        if anchor == anchors[0]:
            p, f = offset, 0.0
        elif anchor == anchors[1]:
            p, f = extent / 2.0 + offset, 0.5
        elif anchor == anchors[2]:
            p, f = extent - offset, 1.0
        else:
            return None
        return p - f * float(size) + float(pivotOff)

    _GRAB_MIN = 24.0

    def _clampOnScreen(self, fullKey, xy):
        if not isinstance(xy, dict):
            return xy
        g = self._geom.get(fullKey)
        stage = Util.stageSize()
        if not g or stage is None:
            return xy
        x = self._clampAxis(xy.get('x'), g.get('w', 0.0), g.get('pox', 0.0), stage[0], self._GRAB_MIN)
        y = self._clampAxis(xy.get('y'), g.get('h', 0.0), g.get('poy', 0.0), stage[1], self._GRAB_MIN)
        if x is None or y is None:
            return xy
        return {'x': int(round(x)), 'y': int(round(y))}

    @staticmethod
    def _clampAxis(origin, size, pivotOff, extent, m):
        try:
            o, size, pivotOff = float(origin), float(size), float(pivotOff)
        except Exception:
            return None
        lo = o - pivotOff
        hi = lo + size
        if hi < m:
            return m - size + pivotOff
        if lo > extent - m:
            return extent - m + pivotOff
        return o

    def reportGeometry(self, fullKey, geom):
        slug = self._index.ownerSlug(fullKey)
        if slug is None or not isinstance(geom, dict):
            return
        g = {}
        for k in ('w', 'h', 'pox', 'poy'):
            try:
                g[k] = float(geom.get(k))
            except Exception:
                g[k] = 0.0
        dragging = fullKey == getattr(self, '_dragKey', None)
        if dragging:
            logError('[drag] geometry report arrived DURING a drag -- gate leaked: ' + str(fullKey))
            return
        self._geom[fullKey] = g
        self._republishPosition(slug, fullKey)

    def _republishPosition(self, slug, fullKey):
        xy = self._resolvePositionFor(slug, fullKey)
        key = None if not isinstance(xy, dict) else (xy.get('x'), xy.get('y'))
        if key == self._posPublished.get(fullKey):
            return
        self._posPublished[fullKey] = key
        self._updateComponent(slug, fullKey, None)

    _DRAG_SNAP = 20.0

    def _registerDragInput(self):
        self._dragKey = None
        self._dragBox = None
        self._dragOrigin = None
        self._dragPivotOff = (0.0, 0.0)
        self._dragGrab = None
        self._dragStage = None
        self._dragInset = None
        self._dragShift = False
        self._dragLast = None
        self._dragStateLast = (False, False)
        events.onMouseEvent(self._onDragMouse)
        events.onKeyEvent(self._onDragKey)
        events.onBattleShown(self._republishPositions)

    def startDrag(self, fullKey, geom=None):
        slug = self._index.ownerSlug(fullKey)
        if slug is None:
            return
        box = {'left': 0.0, 'top': 0.0, 'w': 0.0, 'h': 0.0}
        origin = None
        if isinstance(geom, dict):
            for k in ('left', 'top', 'w', 'h'):
                if k in geom:
                    try:
                        box[k] = float(geom[k])
                    except Exception:
                        pass
            if 'ox' in geom and 'oy' in geom:
                try:
                    origin = (float(geom['ox']), float(geom['oy']))
                except Exception:
                    origin = None
        if origin is None:
            resolved = self._resolvePositionFor(slug, fullKey)
            if isinstance(resolved, dict) and 'x' in resolved and 'y' in resolved:
                try:
                    origin = (float(resolved['x']), float(resolved['y']))
                except Exception:
                    origin = None
        if origin is None:
            origin = (box['left'], box['top'])
        self._dragBox = box
        self._dragOrigin = origin
        self._dragPivotOff = (origin[0] - box['left'], origin[1] - box['top'])
        self._geom[fullKey] = {'w': box['w'], 'h': box['h'],
                               'pox': self._dragPivotOff[0], 'poy': self._dragPivotOff[1]}
        self._dragGrab = None
        self._dragInset = self._screenBoundsOffset(slug, fullKey)
        self._dragStage = Util.stageSize() or (2560.0, 1080.0)
        self._dragLast = None
        self._dragKey = fullKey
        self._publishDragState()

    @staticmethod
    def _clampDragAxis(n, pivotOff, size, extent, near, far):
        lo = pivotOff + (near or 0.0)
        hi = extent - size + pivotOff - (far or 0.0)
        return max(lo, min(n, max(lo, hi)))

    _INSET_EDGES = ('top', 'left', 'right', 'bottom')

    def _screenBoundsOffset(self, slug, fullKey):
        out = {}
        for edge in self._INSET_EDGES:
            out[edge] = 0.0
        node = self._index.node(slug, self._sk(fullKey)) or {}
        spec = node.get('screenBoundsOffset')
        if not isinstance(spec, dict):
            return out
        for edge in self._INSET_EDGES:
            try:
                out[edge] = float(spec.get(edge, 0) or 0)
            except Exception:
                out[edge] = 0.0
        return out

    def stopDrag(self, fullKey=None):
        key = self._dragKey
        last = self._dragLast
        self._dragKey = None
        self._dragGrab = None
        self._publishDragState()
        if key is not None and last is not None:
            self.writePosition(key, None, last[0], last[1])

    def _publishDragState(self):
        state = (self._dragKey is not None, bool(self._dragShift))
        if state == self._dragStateLast:
            return
        self._dragStateLast = state
        self._dh.update(DRAGSTATE_KEY,
                        {'isDragging': state[0], 'isSnapMode': state[1]})

    def _onDragMouse(self, *a, **k):
        try:
            if self._dragKey is None or not a:
                return
            o = a[0]
            if (getattr(o, 'dx', 0) or 0) == 0 \
                    and (getattr(o, 'dy', 0) or 0) == 0:
                return
            cp = getattr(o, 'cursorPosition', None)
            st = self._dragStage
            if cp is None or st is None:
                return
            cx = (cp[0] + 1.0) * 0.5 * st[0]
            cy = (1.0 - cp[1]) * 0.5 * st[1]
            if self._dragGrab is None:
                self._dragGrab = (cx - self._dragOrigin[0],
                                  cy - self._dragOrigin[1])
            nx = cx - self._dragGrab[0]
            ny = cy - self._dragGrab[1]
            if self._dragShift:
                nx = round(nx / self._DRAG_SNAP) * self._DRAG_SNAP
                ny = round(ny / self._DRAG_SNAP) * self._DRAG_SNAP
            offX, offY = self._dragPivotOff
            ins = getattr(self, '_dragInset', None) or {}
            nx = self._clampDragAxis(nx, offX, self._dragBox['w'], st[0],
                                     ins.get('left'), ins.get('right'))
            ny = self._clampDragAxis(ny, offY, self._dragBox['h'], st[1],
                                     ins.get('top'), ins.get('bottom'))
            xy = (int(round(nx)), int(round(ny)))
            if xy == self._dragLast:
                return
            self._dragLast = xy
            self._dh.update(componentKey(self._dragKey),
                            {'value': {'x': xy[0], 'y': xy[1]}, 'visible': True})
        except Exception as e:
            logException('drag move', e)

    def _onDragKey(self, *a, **k):
        try:
            if a:
                self._dragShift = bool(a[0].isShiftDown())
                self._publishDragState()
        except Exception:
            pass

    def _republishPositions(self):
        try:
            for slug in self._index.slugs():
                for storeKey in self._index.positionKeys(slug):
                    self._republishPosition(slug, self._hk(slug, storeKey))
        except Exception as e:
            logException('republish positions', e)

    def _valueOf(self, slug):
        store = self._store
        return lambda key: store.getEffective(slug, key)


    def setPref(self, fullKey, value):
        slug = self._index.ownerSlug(fullKey)
        if slug is None:
            logError('setPref: unknown key ' + str(fullKey))
            return
        self._applyOne(slug, fullKey, value)
        self._recomputeDependents(fullKey)
        if slug == self._index.frameworkSlug():
            self._onFrameworkSettingChanged(fullKey)
        self._scheduleFlush(slug)

    def setPrefHsv(self, fullKey, h, s, v, a):
        r, g, b = ColorMath.hsvToRgb(h, s, v)
        self._setPackedColor(fullKey, a, r, g, b)

    def setPrefRgb(self, fullKey, r, g, b, a):
        self._setPackedColor(fullKey, a, r, g, b)

    def _setPackedColor(self, fullKey, a, r, g, b):
        packed = ColorMath.pack(a, r, g, b)
        slug = self._index.ownerSlug(fullKey)
        if slug is not None and self._store.getEffective(slug, self._sk(fullKey)) == packed:
            return
        self.setPref(fullKey, packed)

    def setPrefs(self, slug, values):
        if not isinstance(values, dict):
            return
        fwSlug = self._index.frameworkSlug()
        touched = []
        for fullKey, value in values.items():
            owner = self._index.ownerSlug(fullKey) or slug
            self._applyOne(owner, fullKey, value)
            touched.append(fullKey)
        for fullKey in touched:
            self._recomputeDependents(fullKey)
            if self._index.ownerSlug(fullKey) == fwSlug:
                self._onFrameworkSettingChanged(fullKey)
        self._scheduleFlush(slug)

    def resetPref(self, fullKey):
        slug = self._index.ownerSlug(fullKey)
        if slug is None:
            return
        storeKey = self._sk(fullKey)
        self._store.remove(slug, storeKey)
        value = self._store.getEffective(slug, storeKey)
        self._updateComponent(slug, fullKey, value)
        self._recomputeDependents(fullKey)
        self._scheduleFlush(slug)

    def resetPosition(self, fullKey):
        slug = self._index.ownerSlug(fullKey)
        storeKey = self._sk(fullKey)
        if slug is None or storeKey not in self._index.positionKeys(slug):
            return
        self._store.removePositionBucket(slug, storeKey, Util.resKey())
        self._updateComponent(slug, fullKey, None)
        self._scheduleFlush(slug)

    def resetAll(self, slug):
        self._store.resetAll(slug)
        for storeKey in self._index.keySet(slug):
            value = self._store.getEffective(slug, storeKey)
            self._updateComponent(slug, self._hk(slug, storeKey), value)
        for storeKey in self._index.keySet(slug):
            self._recomputeDependents(self._hk(slug, storeKey))
        self._scheduleFlush(slug)

    def writePosition(self, fullKey, resKey, x, y):
        slug = self._index.ownerSlug(fullKey)
        if slug is None:
            return
        if not resKey:
            resKey = Util.resKey()
            if not resKey:
                logError('setPosition: stage resolution unavailable for '
                         + str(fullKey))
                return
        storeKey = self._sk(fullKey)
        self._store.writePosition(slug, storeKey, resKey, x, y)
        value = self._store.get(slug, storeKey, {})
        self._updateComponent(slug, fullKey, value)
        self._scheduleFlush(slug)


    def _foldLegacyPositions(self, attempt=1):
        self._cancelTimer('_foldTimer')
        pending = self._collectPendingPositions()
        if not pending:
            return
        key = Util.resKey()
        if key is None:
            if attempt <= 5:
                try:
                    self._foldTimer = callbacks.callback(
                        1.0, lambda: self._foldLegacyPositions(attempt + 1))
                    return
                except Exception:
                    pass
            logError('legacy position fold skipped: stage resolution unavailable')
            return
        reader = self._chatBoxReader
        for slug, fullKey, element in pending:
            try:
                x = reader(element + '_positionX', None)
                y = reader(element + '_positionY', None)
                if x is None or y is None:
                    continue
                self._store.writePosition(slug, fullKey, key, x, y)
                value = self._store.get(slug, fullKey, {})
                self._updateComponent(slug, self._hk(slug, fullKey), value)
                self._scheduleFlush(slug)
                logInfo('legacy position folded: %s [%s] -> %s'
                        % (slug, fullKey, key))
            except Exception as e:
                logException('legacy position fold ' + str(fullKey), e)

    def _warnOrphanLegacyPositions(self):
        section = Util.chatBoxSection()
        if not section:
            return []
        claimed = set()
        for slug in self._index.slugs():
            for entry in self._index.legacyPositions(slug):
                element = entry.get('element')
                if element:
                    claimed.add(element)
        reader = self._chatBoxReader
        suffix = '_positionX'
        orphans = set()
        for key in section.keys():
            if not (isinstance(key, basestring) and key.endswith(suffix)):
                continue
            element = key[:-len(suffix)]
            if not element or element in claimed:
                continue
            if reader(element + '_positionX', None) is None \
                    or reader(element + '_positionY', None) is None:
                continue
            orphans.add(element)
        if orphans:
            logInfo('legacy position(s) no loaded schema claims: %s -- expected '
                    'when those mods are not installed; if one IS installed, its '
                    'schema is missing a legacyPositions entry (element name '
                    'verbatim) and that saved placement will not migrate'
                    % ', '.join(sorted(orphans)))
        return sorted(orphans)

    def _collectPendingPositions(self):
        out = []
        for slug in self._index.slugs():
            if not self._store.wasFresh(slug):
                continue
            for entry in self._index.legacyPositions(slug):
                fullKey = entry.get('key')
                element = entry.get('element')
                if not fullKey or not element:
                    continue
                existing = self._store.get(slug, fullKey, None)
                if isinstance(existing, dict) and existing:
                    continue
                out.append((slug, fullKey, element))
        return out


    def _onFrameworkSettingChanged(self, fullKey):
        fwSlug = self._index.frameworkSlug()
        if fwSlug is None:
            return
        storeKey = self._sk(fullKey)
        value = self._store.getEffective(fwSlug, storeKey)
        if storeKey == SAVE_MODE_KEY:
            self._settings['saveMode'] = value
            logInfo('saveMode -> %s' % value)
        elif storeKey == HOT_RELOAD_KEY:
            self._settings['hotReloadEnabled'] = bool(value)
            logInfo('hotReloadEnabled -> %s' % value)

    def reloadSchemas(self):
        if not self._settings.get('hotReloadEnabled'):
            logInfo('hot-reload requested but disabled '
                    '(ttModConfig.hotReloadEnabled is false)')
            return
        try:
            self._index = SchemaScanner.scan()
            self._store.setIndex(self._index)
            self._store.loadAll()

            self._createSettingComponents()
            self._initialVisibilityPass()
            self._createGroupComponents()
            self._publishShared()
            logInfo('hot-reload: re-scanned %d mod(s)'
                    % len(self._index.displaySlugs()))
        except Exception as e:
            logException('hot-reload failed', e)


    def _sk(self, hubKey):
        return self._index.bareKey(hubKey) or hubKey

    def _hk(self, mod, storeKey):
        return self._index.hubKey(mod, storeKey)

    def _applyOne(self, slug, fullKey, value):
        storeKey = self._sk(fullKey)
        node = self._index.node(slug, storeKey)
        if node is None:
            logError('write: no schema node for ' + str(fullKey))
            return
        validated = Validate.validate(node, value)
        self._store.set(slug, storeKey, validated)
        self._updateComponent(slug, fullKey, validated)

    def _updateComponent(self, slug, fullKey, value):
        installed = self._index.installedMods()
        data = self._buildData(slug, fullKey, value, installed)
        self._dh.update(componentKey(fullKey), data)

    def _recomputeDependents(self, depKey):
        installed = self._index.installedMods()
        for slug, dependentKey in self._index.dependents(depKey):
            if self._index.isGroupKey(dependentKey):
                conds = self._index.groupConditionsFor(slug, dependentKey)
                visible = Conditions.evaluate(
                    conds, self._valueOf(slug), installed)
                self._dh.update(componentKey(dependentKey), {'visible': visible})
                continue
            conds = self._index.conditionsFor(slug, dependentKey)
            visible = Conditions.evaluate(conds, self._valueOf(slug), installed)
            value = self._store.getEffective(slug, self._sk(dependentKey))
            data = self._buildData(slug, dependentKey, value, installed, visible)
            self._dh.update(componentKey(dependentKey), data)


    def _scheduleFlush(self, slug):
        if self._settings['saveMode'] == 'dev':
            return
        if self._flushScheduled:
            return
        self._flushScheduled = True
        try:
            self._flushTimer = callbacks.callback(_DEBOUNCE_SECONDS,
                                                  self._flushPending)
        except Exception:
            self._flushScheduled = False
            self._store.flushAll()

    def _flushPending(self):
        self._cancelTimer('_flushTimer')
        self._flushScheduled = False
        try:
            self._store.flushAll()
        except Exception as e:
            logException('flushPending', e)


    def _subscribeLifecycle(self):
        events.onBattleEnd(self._onBattleBoundary)
        events.onBattleQuit(self._onBattleBoundary)

    def _onBattleBoundary(self, *args):
        if self._cursor is not None:
            try:
                self._cursor.releaseNow()
            except Exception as e:
                logException('battle-boundary cursor release', e)
        try:
            self._store.flushAll()
        except Exception as e:
            logException('battle-boundary flush', e)

    def shutdown(self):
        for name in ('_flushTimer', '_foldTimer', '_retryTimer'):
            self._cancelTimer(name)
        self._flushScheduled = False
        if self._cursor is not None:
            try:
                self._cursor.shutdown()
            except Exception as e:
                logException('cursor shutdown', e)
        if self._store is not None:
            try:
                self._store.shutdown()
            except Exception as e:
                logException('shutdown', e)


def _loadFrameworkSettings():
    settings = dict(_FRAMEWORK_DEFAULTS)
    prefsDir = Util.prefsDir()

    try:
        data = Util.readJson(_u1.path.join(prefsDir, _FRAMEWORK_JSON))
        if isinstance(data, dict):
            for k in settings:
                if k in data:
                    settings[k] = data[k]
    except Exception:
        pass

    try:
        store = Util.readJson(_u1.path.join(prefsDir, _frameworkStoreFile()))
        prefs = store.get('prefs', {}) if isinstance(store, dict) else {}
        for bare, dotted in _FRAMEWORK_BOOTSTRAP:
            v = Util.getNested(prefs, dotted, _SENTINEL)
            if v is not _SENTINEL:
                settings[bare] = v
    except Exception:
        pass

    return settings


def _frameworkStoreFile():
    directory = Util.schemasDir()
    for name in sorted(Util.listDir(directory)):
        if not name.endswith(SchemaScanner.SCHEMA_SUFFIX):
            continue
        try:
            data = Util.readJson(_u1.path.join(directory, name))
            if isinstance(data, dict) and data.get('framework') and data.get('id'):
                return data['id'] + '.json'
        except Exception:
            continue
    return ''


def _makeLegacyReader():
    def reader(key, default):
        try:
            return ui.getUserPrefs('chatBoxWidth', key, default)
        except Exception:
            return default
    return reader


def _makeLegacyReaderFor(chatBoxReader):
    frameworkReader = _makeFrameworkLegacyReader()

    def factory(slug):
        if slug == FRAMEWORK_SLUG:
            return frameworkReader
        return chatBoxReader
    return factory


def _makeFrameworkLegacyReader():
    data = Util.readJson(_u1.path.join(Util.prefsDir(), _FRAMEWORK_JSON))
    if not isinstance(data, dict):
        data = {}

    def reader(key, default):
        return data.get(key, default)
    return reader


gFramework = None
if _u1.environ.get('TTARO_NO_AUTOSTART') != '1':
    gFramework = Framework()
    gFramework.start()
