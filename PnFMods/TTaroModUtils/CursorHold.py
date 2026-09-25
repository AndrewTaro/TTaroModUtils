# -*- coding: utf-8 -*-

import Util
from Util import logInfo, logException


HOLD_ENABLED = True


class CursorHold(object):

    def __init__(self):
        self._want = False
        self._suppressApplied = False
        self._warned = set()
        try:
            self.releaseNow()
        except Exception as e:
            logException('CursorHold startup clear', e)


    def _warnOnce(self, key, exc):
        if key in self._warned:
            return
        self._warned.add(key)
        logException('CursorHold: ' + key, exc)

    def _handle(self):
        return Util._u8()

    def _apply(self, state):
        handle = self._handle()
        if handle is None:
            return False
        try:
            Util._u9(handle, state)
            return True
        except Exception as e:
            self._warnOnce('cursor flag write failed', e)
            return False

    def _ch(self):
        return Util._u7()

    def _applySuppress(self, state):
        state = bool(state)
        if state == self._suppressApplied:
            return
        ch = self._ch()
        if ch is None:
            if not state:
                self._suppressApplied = False
            return
        try:
            Util._u10(ch, state)
            self._suppressApplied = state
        except Exception as e:
            self._warnOnce('input suppress toggle failed', e)
            if not state:
                self._suppressApplied = False


    def request(self, want):
        want = (want is True) or (want == 1)
        if want == self._want:
            return
        logInfo('[cursor] hold %s%s' % (
            'requested' if want else 'released',
            '' if HOLD_ENABLED else ' (DISABLED by kill switch)'))
        self._want = want
        if want:
            if not HOLD_ENABLED:
                self._want = False
                return
            self._apply(True)
            self._applySuppress(True)
        else:
            self.releaseNow()

    def releaseNow(self):
        self._want = False
        self._apply(False)
        self._applySuppress(False)

    def shutdown(self):
        try:
            self.releaseNow()
        except Exception as e:
            logException('CursorHold shutdown', e)

