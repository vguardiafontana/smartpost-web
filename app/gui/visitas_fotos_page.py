from __future__ import annotations

import asyncio
import logging

from PySide6.QtCore import QObject, Signal, Slot, QThread
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QAbstractItemView

from app.core.config import load_config
from app.gui.busqueda_guias_page import BusquedaGuiasPage, CopyableTableWidget
from app.visitas.fotos import search_visit_photos


class VisitPhotosWorker(QObject):
    progress = Signal(str)
    finished = Signal(bool, object)

    @Slot()
    def run(self):
        try:
            result = asyncio.run(search_visit_photos(load_config(), logging.getLogger('VISITAS_FOTOS'), progress=self.progress.emit))
            self.finished.emit(True, result)
        except Exception:
            logging.getLogger('VISITAS_FOTOS').exception('Consulta fallida')
            self.finished.emit(False, {})


class VisitasFotosPage(BusquedaGuiasPage):
    # Reutiliza la tabla copiable, enlaces y ordenación de Búsqueda de guías.
    COLUMNS = [column for column in BusquedaGuiasPage.COLUMNS if column[0] not in ('distribuidor_dni', 'distribuidor_telefono', '__action__')] + [
        ('fotos_resumen', 'Fotos / visitas', 130), ('fotos_pendientes', 'Pendientes', 100),
        ('__action__', 'Acción', 130),
    ]

    def _build_ui(self):
        self.result = None
        self.choice = 'No'
        root = QVBoxLayout(self)
        nav = QHBoxLayout()
        self.back_btn = QPushButton('← Inicio')
        self.back_btn.clicked.connect(self.back_requested.emit)
        title = QLabel('Visitas sin foto')
        title.setStyleSheet('font-size:22px;font-weight:800;')
        nav.addWidget(self.back_btn); nav.addWidget(title); nav.addStretch()
        root.addLayout(nav)
        help_text = QLabel('Pedidos ingresados hoy a planta. Cada visita necesita su foto: 2.ª visita, al menos 2 fotos; 3.ª visita, al menos 3.')
        help_text.setWordWrap(True)
        root.addWidget(help_text)
        controls = QHBoxLayout()
        controls.addWidget(QLabel('Fotos de la visita:'))
        self.yes_btn = QPushButton('Completas'); self.no_btn = QPushButton('Pendientes')
        for button, value in ((self.yes_btn, 'Sí'), (self.no_btn, 'No')):
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, value=value: self._choose(value))
            controls.addWidget(button)
        self.no_btn.setChecked(True)
        self.unknown_btn = QPushButton('Sin verificar (0)')
        self.unknown_btn.setCheckable(True)
        self.unknown_btn.clicked.connect(lambda: self._choose('Sin verificar'))
        controls.addWidget(self.unknown_btn)
        self.search_btn = QPushButton('Consultar visitas de hoy')
        self.search_btn.clicked.connect(self._search)
        controls.addWidget(self.search_btn); controls.addStretch()
        root.addLayout(controls)
        self.summary = QLabel('Listo para consultar.')
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        self.table = CopyableTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([c[1] for c in self.COLUMNS])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        for i, (_, _, width) in enumerate(self.COLUMNS):
            self.table.setColumnWidth(i, width)
        root.addWidget(self.table, 1)

    def _choose(self, choice):
        self.choice = choice
        self.yes_btn.setChecked(choice == 'Sí')
        self.no_btn.setChecked(choice == 'No')
        self.unknown_btn.setChecked(choice == 'Sin verificar')
        if self.result is not None:
            rows = [r for r in self.result['rows'] if r['foto'] == choice]
            self._render_rows(rows)
            self.summary.setText(f"{self.result['date']} · {len(rows)} visitas · Foto: {choice} · {self.result['total']} revisadas · {self.result['unverified']} sin verificar")

    def _search(self):
        if self.thread is not None:
            return
        self.result = None
        self._clear_results()
        self.unknown_btn.setText('Sin verificar (0)')
        self.search_btn.setEnabled(False)
        self.back_btn.setEnabled(False)
        self.summary.setText('Buscando visitas de hoy…')
        self.thread = QThread(self)
        self.worker = VisitPhotosWorker()
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.summary.setText)
        self.worker.finished.connect(self._finished)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self._clear_worker)
        self.thread.start()

    def _finished(self, ok, result):
        self.search_btn.setEnabled(True)
        self.back_btn.setEnabled(True)
        if not ok:
            self.summary.setText('No se pudo completar la consulta. Volvé a consultar.')
            return
        self.result = result
        self.unknown_btn.setText(f"Sin verificar ({result['unverified']})")
        self._choose(self.choice)
