# -*- coding: utf-8 -*-

from Util import logError, logException

PREFIX = 'modPrefs.'
REGISTRY_KEY = 'modPrefs.registry'
INSTALLED_KEY = 'modPrefs.installedMods'
FRAMEWORK_KEY = 'modPrefs.framework'
UISTATE_KEY = 'modPrefs.uiState'
DRAGSTATE_KEY = 'modPrefs.dragState'


def componentKey(fullKey):
    return PREFIX + fullKey


class DataHub(object):

    def __init__(self):
        self._entityByKey = {}

    def create(self, key, data):
        try:
            if key in self._entityByKey:
                self.update(key, data)
                return self._entityByKey[key]
            entityId = ui.createUiElement()
            ui.addDataComponentWithId(entityId, key, dict(data))
            self._entityByKey[key] = entityId
            return entityId
        except Exception as e:
            logException('DataHub.create ' + str(key), e)
            return None

    def update(self, key, data):
        entityId = self._entityByKey.get(key)
        if entityId is None:
            self.create(key, data)
            return
        try:
            ui.updateUiElementData(entityId, dict(data))
        except Exception as e:
            logException('DataHub.update ' + str(key), e)

    def delete(self, key):
        entityId = self._entityByKey.pop(key, None)
        if entityId is None:
            return
        try:
            ui.deleteUiElement(entityId)
        except Exception as e:
            logException('DataHub.delete ' + str(key), e)

    def has(self, key):
        return key in self._entityByKey

    def entityId(self, key):
        return self._entityByKey.get(key)

    def keys(self):
        return list(self._entityByKey.keys())
