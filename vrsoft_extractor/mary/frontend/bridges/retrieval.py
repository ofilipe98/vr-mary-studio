"""Qt presentation for the retrieval service; the service owns search configuration."""
from __future__ import annotations

import threading
from PySide6.QtCore import QObject, Property, Signal, Slot


class RetrievalBridge(QObject):
    changed = Signal()
    _progress = Signal(str)
    _finished = Signal(str)

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._busy = False
        self._status = "Modelo local opcional; preparo exige download explícito."
        self._progress.connect(self._on_progress)
        self._finished.connect(self._on_finished)

    @Property('QVariantMap', notify=changed)
    def configuration(self):
        return self.service.configuration

    @Property(bool, notify=changed)
    def busy(self):
        return self._busy

    @Property(str, notify=changed)
    def status(self):
        return self._status

    @Slot(str, str, bool)
    def configure(self, mode, model, relations):
        if not self._busy:
            self.service.configure(mode=mode, model=model, relations=relations)
            self._status = self.service.configuration['diagnostic']
            self.changed.emit()

    @Slot()
    def prepare(self):
        self._start(True)

    @Slot()
    def reindex(self):
        self._start(False)

    def _start(self, download):
        if self._busy:
            return
        self._busy = True
        self._status = "Preparando modelo e índice…" if download else "Atualizando índice…"
        self.changed.emit()
        def work():
            try:
                def progress(name, done, total):
                    self._progress.emit(f"{name}: {done * 100 // max(total, 1)}%")
                result = self.service.prepare_semantic(progress) if download else self.service.reindex(progress)
                self._finished.emit(f"Índice pronto: {result['documents']} documentos; {result['computed']} vetores calculados.")
            except Exception as exc:
                self._finished.emit(f"Falha: {exc}")
        threading.Thread(target=work, name="semantic-setup", daemon=True).start()

    @Slot(str)
    def _on_progress(self, text):
        self._status = text
        self.changed.emit()

    @Slot(str)
    def _on_finished(self, text):
        self._busy = False
        self._status = text
        self.changed.emit()
