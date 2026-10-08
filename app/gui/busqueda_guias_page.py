from __future__ import annotations

import os
import subprocess
import html
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QThread, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView
)

from app.cambio_estado.service import extract_identifiers
from app.gui.error_dialog import ErrorDialog
from app.gui.workers import BusquedaGuiasWorker


class CopyableTableWidget(QTableWidget):
    """Tabla de sólo lectura que permite copiar una o varias celdas con Ctrl+C."""

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Copy):
            indexes = sorted(self.selectedIndexes(), key=lambda i: (i.row(), i.column()))
            if not indexes:
                return
            rows = {}
            for index in indexes:
                rows.setdefault(index.row(), {})[index.column()] = index.data() or ""
            lines = []
            for row_idx in sorted(rows):
                cols = rows[row_idx]
                start = min(cols)
                end = max(cols)
                lines.append("\t".join(str(cols.get(c, "")) for c in range(start, end + 1)))
            QGuiApplication.clipboard().setText("\n".join(lines))
            return
        super().keyPressEvent(event)


class BusquedaGuiasPage(QWidget):
    back_requested = Signal()

    COLUMNS = [
        ("guia", "Nro Guía", 90),
        ("guia_agente", "Guía Agente", 155),
        ("remito", "Remito", 120),
        ("cliente", "Cliente", 190),
        ("servicio", "Servicio", 95),
        ("destinatario", "Destinatario", 190),
        ("domicilio", "Domicilio", 245),
        ("localidad", "Localidad", 135),
        ("provincia", "Provincia", 130),
        ("codigo_postal", "Código postal", 95),
        ("telefono", "Teléfono", 125),
        ("foto", "Foto", 70),
        ("estado", "Estado", 190),
        ("distribuidor_nombre", "Distribuidor", 200),
        ("distribuidor_dni", "DNI distribuidor", 115),
        ("distribuidor_telefono", "Tel. distribuidor", 125),
        ("__action__", "Acción", 125),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread = None
        self.worker = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(12)

        nav = QHBoxLayout()
        back = QPushButton("← Inicio")
        back.clicked.connect(self.back_requested.emit)
        title = QLabel("Búsqueda de guías")
        title.setStyleSheet("font-size:22px;font-weight:800;")
        nav.addWidget(back)
        nav.addWidget(title)
        nav.addStretch(1)
        root.addLayout(nav)

        help_text = QLabel(
            "Pegá una o varias guías, remitos o Guías Agente. SmartPost busca cada envío en Epresis "
            "y muestra todos los resultados en una tabla."
        )
        help_text.setWordWrap(True)
        help_text.setStyleSheet("color:#5b6472;")
        root.addWidget(help_text)

        self.input = QTextEdit()
        self.input.setPlaceholderText("Ejemplo:\n6190808\n48081585158\n2000015167962061")
        self.input.setMaximumHeight(120)
        root.addWidget(self.input)

        controls = QHBoxLayout()
        self.search_btn = QPushButton("BUSCAR")
        self.search_btn.setMinimumHeight(40)
        self.search_btn.clicked.connect(self._search)
        self.summary = QLabel("Listo para buscar.")
        self.summary.setStyleSheet("color:#5b6472;")
        controls.addWidget(self.search_btn)
        controls.addWidget(self.summary)
        controls.addStretch(1)
        root.addLayout(controls)

        self.table = CopyableTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([label for _, label, _ in self.COLUMNS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.Interactive)
        for i, (_, _, width) in enumerate(self.COLUMNS):
            self.table.setColumnWidth(i, width)
        self.table.setStyleSheet(
            "QTableWidget{background:#d9dde2;color:#111111;gridline-color:#bcc2c9;alternate-background-color:#e4e7eb;}"
            "QTableWidget::item{padding:5px;color:#111111;background:#d9dde2;}"
            "QTableWidget::item:alternate{background:#e4e7eb;}"
            "QTableWidget::item:selected{background:#9fb9d6;color:#000000;}"
            "QHeaderView::section{background:#c7ccd2;color:#111111;font-weight:700;padding:7px;border:0;border-right:1px solid #aeb5bd;border-bottom:1px solid #aeb5bd;}"
        )
        root.addWidget(self.table, 1)

    def _set_busy(self, busy: bool):
        self.search_btn.setEnabled(not busy)
        self.input.setEnabled(not busy)
        self.search_btn.setText("Buscando…" if busy else "BUSCAR")

    def _clear_results(self):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self.table.setSortingEnabled(True)

    def _search(self):
        identifiers = extract_identifiers(self.input.toPlainText())
        if not identifiers:
            QMessageBox.warning(self, "Sin pedidos", "Pegá al menos una guía, remito o Guía Agente.")
            return
        if self.thread is not None:
            return
        self._clear_results()
        self._set_busy(True)
        self.summary.setText(f"Buscando {len(identifiers)} identificador(es)…")
        self.thread = QThread(self)
        self.worker = BusquedaGuiasWorker(identifiers)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._finished)
        self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self._clear_worker)
        self.thread.start()

    def _clear_worker(self):
        self.thread = None
        self.worker = None

    def _finished(self, ok: bool, rows, detail: str):
        self._set_busy(False)
        if not ok:
            self.summary.setText("Error en la búsqueda.")
            ErrorDialog(detail, self).exec()
            return
        rows = list(rows or [])
        self._render_rows(rows)
        found = sum(1 for r in rows if not r.get("error"))
        errors = len(rows) - found
        self.summary.setText(f"{found} envío(s) encontrado(s) · {errors} sin resolver/error(es).")

    def _render_rows(self, rows):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            if row.get("error"):
                self._render_error_row(r, row)
                continue
            for c, (key, _, _) in enumerate(self.COLUMNS):
                if key == "__action__":
                    btn = QPushButton("Abrir guía")
                    url = str(row.get("show_url") or "")
                    btn.setEnabled(bool(url))
                    btn.clicked.connect(lambda checked=False, u=url: self._open_in_chrome(u))
                    self.table.setCellWidget(r, c, btn)
                    continue
                if key == "distribuidor_nombre":
                    value = row.get(key, "") or row.get("distribuidor_raw", "")
                    dist_url = str(row.get("distribuidor_url") or "")
                    # Dejamos el QTableWidgetItem debajo para que Ctrl+C siga copiando
                    # el nombre aun cuando visualmente haya un enlace clickeable encima.
                    item = QTableWidgetItem(str(value or "—"))
                    item.setToolTip(dist_url or str(value or ""))
                    item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                    self.table.setItem(r, c, item)
                    if dist_url and value:
                        link = QLabel(f'<a href="{html.escape(dist_url, quote=True)}">{html.escape(str(value))}</a>')
                        link.setTextInteractionFlags(Qt.TextBrowserInteraction)
                        link.setOpenExternalLinks(False)
                        link.setStyleSheet("QLabel{background:transparent;color:#111111;padding:4px;} QLabel a{color:#0b57d0;}")
                        link.setToolTip(dist_url)
                        link.linkActivated.connect(self._open_in_chrome)
                        self.table.setCellWidget(r, c, link)
                    continue
                else:
                    value = row.get(key, "")
                item = QTableWidgetItem(str(value or "—"))
                item.setToolTip(str(value or ""))
                item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                self.table.setItem(r, c, item)
        self.table.resizeRowsToContents()
        self.table.setSortingEnabled(True)

    def _render_error_row(self, row_index: int, row: dict):
        entrada = str(row.get("entrada") or "")
        error = str(row.get("error") or "No encontrado")
        first = QTableWidgetItem(entrada or "—")
        first.setToolTip(error)
        self.table.setItem(row_index, 0, first)
        second = QTableWidgetItem(f"ERROR: {error}")
        second.setToolTip(error)
        self.table.setItem(row_index, 1, second)
        for c in range(2, len(self.COLUMNS)):
            self.table.setItem(row_index, c, QTableWidgetItem("—"))

    @staticmethod
    def _open_in_chrome(url: str):
        if not url:
            return
        candidates = [
            Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        ]
        for chrome in candidates:
            if str(chrome) and chrome.exists():
                try:
                    subprocess.Popen([str(chrome), url])
                    return
                except Exception:
                    pass
        QDesktopServices.openUrl(QUrl(url))
