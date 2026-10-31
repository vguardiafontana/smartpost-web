from __future__ import annotations

from PySide6.QtCore import Signal, QThread, QDate
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QGroupBox,
    QComboBox, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QDateEdit
)

from app.cambio_estado.states import STATES
from app.cambio_estado.service import extract_identifiers
from app.gui.error_dialog import ErrorDialog
from app.gui.workers import CambioEstadoV2Worker
from app.core.dates import operation_date


class CambioEstadoV2Page(QWidget):
    back_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread = None
        self.worker = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self); root.setContentsMargins(8,8,8,8); root.setSpacing(12)
        top = QHBoxLayout()
        back = QPushButton("← Inicio"); back.clicked.connect(self.back_requested.emit)
        title = QLabel("Cambio de estado v2"); title.setStyleSheet("font-size:22px;font-weight:800;")
        top.addWidget(back); top.addWidget(title); top.addStretch(1); root.addLayout(top)

        info = QLabel(
            "Nuevo flujo por Rendición de Chofer. SmartPost resuelve cada pedido, identifica su distribuidor, "
            "busca la planilla de la fecha seleccionada, verifica que el pedido esté dentro de esa planilla y agrupa los cambios por chofer/planilla."
        )
        info.setWordWrap(True); info.setStyleSheet("color:#c5b6ff;background:#303244;padding:9px;border-radius:6px;")
        root.addWidget(info)

        controls_box = QGroupBox("Nuevo estado e identificadores")
        cv = QVBoxLayout(controls_box)
        state_row = QHBoxLayout(); state_row.addWidget(QLabel("Estado nuevo:"))
        self.state_combo = QComboBox()
        for state_id, label in STATES:
            self.state_combo.addItem(label, state_id)
        self.state_combo.setMinimumWidth(360)
        state_row.addWidget(self.state_combo); state_row.addStretch(1); cv.addLayout(state_row)
        day = operation_date()
        self.date_edit = QDateEdit(QDate(day.year, day.month, day.day))
        self.date_edit.setCalendarPopup(True); self.date_edit.setDisplayFormat("dd/MM/yyyy")
        date_row = QHBoxLayout(); date_row.addWidget(QLabel("Fecha de planilla y cambio:"))
        date_row.addWidget(self.date_edit); date_row.addStretch(1); cv.addLayout(date_row)

        self.bulk_input = QTextEdit()
        self.bulk_input.setPlaceholderText(
            "Pegá una mezcla de N° de guía, Remito o Guía Agente.\n"
            "SmartPost buscará automáticamente el chofer y la planilla correspondiente."
        )
        self.bulk_input.setMinimumHeight(120); cv.addWidget(self.bulk_input)
        buttons = QHBoxLayout()
        self.change_btn = QPushButton("CAMBIAR ESTADO V2")
        self.change_btn.setProperty('primary', True)
        self.change_btn.setMinimumHeight(42); self.change_btn.setStyleSheet("font-weight:800;")
        self.change_btn.clicked.connect(self._change)
        clear = QPushButton("Limpiar"); clear.clicked.connect(self._clear)
        buttons.addWidget(self.change_btn); buttons.addWidget(clear); buttons.addStretch(1); cv.addLayout(buttons)
        root.addWidget(controls_box)

        result_box = QGroupBox("Resultado")
        rv = QVBoxLayout(result_box)
        self.summary_label = QLabel("Todavía no se ejecutó ningún cambio.")
        self.summary_label.setWordWrap(True); rv.addWidget(self.summary_label)
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels([
            "Entrada", "Tipo", "Guía", "Remito", "Guía Agente", "Estado anterior",
            "Distribuidor", "Planilla", "Rendición", "Resultado"
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        for c in (0,1,2,3,4,5,7,8,9):
            self.table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        rv.addWidget(self.table); root.addWidget(result_box, 1)

        self.logs = QTextEdit(); self.logs.setReadOnly(True); self.logs.setMaximumHeight(165)
        self.logs.setStyleSheet("font-family:Consolas,monospace;font-size:10px;"); root.addWidget(self.logs)

    def _clear(self):
        self.bulk_input.clear(); self.logs.clear(); self.table.setRowCount(0)
        self.summary_label.setText("Todavía no se ejecutó ningún cambio.")

    def _set_busy(self, busy: bool):
        self.change_btn.setEnabled(not busy)
        self.bulk_input.setEnabled(not busy)
        self.state_combo.setEnabled(not busy)
        self.date_edit.setEnabled(not busy)

    def _change(self):
        identifiers = extract_identifiers(self.bulk_input.toPlainText())
        if not identifiers:
            QMessageBox.warning(self, "Faltan identificadores", "Pegá al menos un número de guía, remito o Guía Agente.")
            return
        state_id = int(self.state_combo.currentData())
        state_text = self.state_combo.currentText()
        selected_date = self.date_edit.date().toString("yyyy-MM-dd")
        confirm = QMessageBox.question(
            self,
            "Confirmar Cambio de estado v2",
            f"Se procesarán {len(identifiers)} entrada(s) con el estado:\n\n{state_text}\n\n"
            f"Fecha: {self.date_edit.date().toString('dd/MM/yyyy')}.\n"
            "Se usará Rendición de Chofer y se agruparán los pedidos por planilla. ¿Continuar?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        self.logs.clear(); self.table.setRowCount(0); self._set_busy(True)
        self.summary_label.setText(f"Procesando {len(identifiers)} entrada(s) → {state_text}…")
        self.logs.append(f"Iniciando Cambio de estado v2 a {state_text}…")
        self.thread = QThread(self)
        self.worker = CambioEstadoV2Worker(identifiers, state_id, selected_date)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.log_line.connect(self.logs.append)
        self.worker.finished.connect(self._finished)
        self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def _finished(self, ok: bool, rows, detail: str):
        self._set_busy(False)
        if not ok:
            ErrorDialog(detail, self).exec(); return
        rows = list(rows or [])
        self._render_rows(rows)
        changed_ok = sum(1 for r in rows if r.get("resolution_status") == "resolved" and r.get("change_status") == "ok")
        already_assigned = sum(1 for r in rows if r.get("resolution_status") == "resolved" and r.get("change_status") == "already_assigned")
        warnings = sum(1 for r in rows if r.get("resolution_status") == "resolved" and r.get("change_status") == "warning")
        change_err = sum(1 for r in rows if r.get("resolution_status") == "resolved" and r.get("change_status") == "error")
        unresolved = sum(1 for r in rows if r.get("resolution_status") in {"unresolved", "error"})
        duplicates = sum(1 for r in rows if r.get("resolution_status") == "duplicate")
        self.summary_label.setText(
            f"Terminado: {changed_ok} realizado(s) · {already_assigned} estado ya asignado · "
            f"{warnings} advertencia(s) · {change_err} error(es) · {unresolved} sin resolver · {duplicates} duplicada(s)."
        )
        self.logs.append(self.summary_label.text())
        QMessageBox.information(
            self, "Cambio de estado v2 terminado",
            f"{changed_ok} cambio(s) realizado(s) y verificado(s).\n"
            f"{already_assigned} estado(s) ya asignado(s).\n"
            f"{warnings} cambio(s) aceptado(s) sin verificación final.\n"
            f"{change_err} error(es).\n{unresolved} entrada(s) sin resolver.\n{duplicates} duplicada(s)."
        )

    def _render_rows(self, rows):
        self.table.setRowCount(len(rows))
        for r, item in enumerate(rows):
            state_text = str(item.get("current_state") or "")
            status = str(item.get("resolution_status") or "")
            if status == "resolved":
                cs = item.get("change_status")
                if cs == "ok":
                    status = "OK"
                elif cs == "already_assigned":
                    status = "Estado ya asignado"
                elif cs == "warning":
                    status = f"ADVERTENCIA: {item.get('change_message','')}"
                elif cs == "error":
                    status = f"ERROR: {item.get('change_message','')}"
                else:
                    status = "Sin resultado"
            elif status == "duplicate":
                status = "Duplicada"
            else:
                status = str(item.get("message") or status)
            distributor = str(item.get("distribuidor_nombre") or item.get("distribuidor_dni") or item.get("distribuidor_id") or "")
            values = [
                item.get("input_value", ""), item.get("detected_type", ""), item.get("guia", ""),
                item.get("remito", ""), item.get("guia_agente", ""), state_text, distributor,
                item.get("planilla_id", ""), item.get("nro_rendicion", ""), status,
            ]
            for c, value in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(str(value)))
