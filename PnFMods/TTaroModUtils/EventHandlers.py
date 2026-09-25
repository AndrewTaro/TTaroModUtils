# -*- coding: utf-8 -*-

import Util
from Util import logInfo, logError, logException


class EventHandlers(object):

    def __init__(self, framework):
        self._fw = framework
        self._registered = False

    def register(self):
        chan = Util._u6()
        if chan is None:
            logError('write channel unavailable -- writes disabled; '
                     'view renders read-only (sentinel-pump fallback TODO)')
            return False
        try:
            pairs = [
                ('mod.setPref', self._onSetPref),
                ('mod.setPrefHsv', self._onSetPrefHsv),
                ('mod.setPrefRgb', self._onSetPrefRgb),
                ('mod.setPrefs', self._onSetPrefs),
                ('mod.resetPref', self._onResetPref),
                ('mod.resetPosition', self._onResetPosition),
                ('mod.resetAll', self._onResetAll),
                ('mod.setPosition', self._onSetPosition),
                ('mod.reportGeometry', self._onReportGeometry),
                ('mod.startDragging', self._onStartDragging),
                ('mod.stopDragging', self._onStopDragging),
                ('mod.setUiState', self._onSetUiState),
                ('mod.setCursorHold', self._onSetCursorHold),
                ('mod.reloadSchemas', self._onReloadSchemas),
            ]
            for name, fn in pairs:
                Util._u11(chan, name, fn)
            self._registered = True
            logInfo('write-path handlers registered')
            return True
        except Exception as e:
            logException('handler registration failed', e)
            return False


    def _onSetPref(self, fullKey, value=None):
        try:
            self._fw.setPref(fullKey, value)
        except Exception as e:
            logException('mod.setPref ' + str(fullKey), e)

    def _onSetPrefHsv(self, fullKey, h=0, s=0, v=0, a=255):
        try:
            self._fw.setPrefHsv(fullKey, h, s, v, a)
        except Exception as e:
            logException('mod.setPrefHsv ' + str(fullKey), e)

    def _onSetPrefRgb(self, fullKey, r=0, g=0, b=0, a=255):
        try:
            self._fw.setPrefRgb(fullKey, r, g, b, a)
        except Exception as e:
            logException('mod.setPrefRgb ' + str(fullKey), e)

    def _onSetPrefs(self, slug, values=None):
        try:
            self._fw.setPrefs(slug, values or {})
        except Exception as e:
            logException('mod.setPrefs ' + str(slug), e)

    def _onResetPref(self, fullKey):
        try:
            self._fw.resetPref(fullKey)
        except Exception as e:
            logException('mod.resetPref ' + str(fullKey), e)

    def _onResetPosition(self, fullKey):
        try:
            self._fw.resetPosition(fullKey)
        except Exception as e:
            logException('mod.resetPosition ' + str(fullKey), e)

    def _onResetAll(self, slug):
        try:
            self._fw.resetAll(slug)
        except Exception as e:
            logException('mod.resetAll ' + str(slug), e)

    def _onSetPosition(self, fullKey, resKey=None, x=0, y=0):
        try:
            self._fw.writePosition(fullKey, resKey, x, y)
        except Exception as e:
            logException('mod.setPosition ' + str(fullKey), e)

    def _onReportGeometry(self, fullKey, geom=None):
        try:
            self._fw.reportGeometry(fullKey, geom or {})
        except Exception as e:
            logException('mod.reportGeometry ' + str(fullKey), e)

    def _onStartDragging(self, fullKey, geom=None):
        try:
            self._fw.startDrag(fullKey, geom)
        except Exception as e:
            logException('mod.startDragging ' + str(fullKey), e)

    def _onStopDragging(self, fullKey=None):
        try:
            self._fw.stopDrag(fullKey)
        except Exception as e:
            logException('mod.stopDragging ' + str(fullKey), e)

    def _onSetUiState(self, path, value=None):
        try:
            self._fw.setUiState(path, value)
        except Exception as e:
            logException('mod.setUiState ' + str(path), e)

    def _onSetCursorHold(self, want=False):
        try:
            self._fw.setCursorHold(want)
        except Exception as e:
            logException('mod.setCursorHold ' + str(want), e)

    def _onReloadSchemas(self, *args):
        try:
            self._fw.reloadSchemas()
        except Exception as e:
            logException('mod.reloadSchemas', e)
