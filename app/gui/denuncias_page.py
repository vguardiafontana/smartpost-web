from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QDate, QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QGroupBox, QFormLayout, QLineEdit,
    QDateEdit, QComboBox, QTextEdit, QMessageBox, QCheckBox, QScrollArea, QSizePolicy
)

from app.core.config import load_config, resolve_path
from app.denuncias.narratives import ShipmentLine, generate_unknown_circumstances
from app.denuncias.input_parser import parse_identifiers
from app.denuncias.history import downloaded_reports
from app.gui.denuncias_messages_dialog import DenunciasMessagesDialog
from app.gui.error_dialog import ErrorDialog
from app.gui.workers import DenunciasLookupWorker, DenunciasSubmitWorker


class DenunciasPage(QWidget):
    back_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lookup_thread = None
        self.lookup_worker = None
        self.submit_thread = None
        self.submit_worker = None
        self.shipments: list[dict] = []
        self._latest_denuncia = None
        self._pending_submit: bool | None = None
        self._build_ui()

    def _build_ui(self):
        # La página es scrollable: así la ventana principal se puede achicar o
        # agrandar libremente desde cualquier borde/esquina, incluso en pantallas
        # chicas, sin que los formularios impongan un tamaño mínimo gigante.
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        content = QWidget()
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        root = QVBoxLayout(content); root.setContentsMargins(8, 8, 8, 8); root.setSpacing(12)
        top = QHBoxLayout()
        back = QPushButton("← Inicio"); back.clicked.connect(self.back_requested.emit)
        title = QLabel("Denuncias de siniestro"); title.setStyleSheet("font-size:22px;font-weight:800;")
        top.addWidget(back); top.addWidget(title); top.addStretch(1)
        root.addLayout(top)
        actions = QHBoxLayout()
        self.messages_btn = QPushButton('Ver mensajes')
        self.messages_btn.setToolTip('Mensajes por seller de la última denuncia finalizada.')
        self.messages_btn.clicked.connect(self._open_messages)
        self.downloads_btn = QPushButton('Ver denuncias descargadas')
        self.downloads_btn.setToolTip('Abre la carpeta con todos los PDF en el Explorador de Windows.')
        self.downloads_btn.clicked.connect(self._open_downloads)
        actions.addWidget(self.messages_btn); actions.addWidget(self.downloads_btn); actions.addStretch()
        root.addLayout(actions)

        hint = QLabel(
            "Pegá todos los números que tengas. Pueden ser N° de guía SmartPost, Remito o Guía Agente. "
            "No hace falta indicar cuál es cuál ni cargar el seller: SmartPost los busca en Epresis automáticamente."
        )
        hint.setWordWrap(True); hint.setStyleSheet("color:#a5a7ba;")
        root.addWidget(hint)

        input_box = QGroupBox("Pedidos siniestrados")
        iv = QVBoxLayout(input_box)
        self.bulk_input = QTextEdit()
        self.bulk_input.setPlaceholderText(
            "Pegá uno o varios identificadores, uno debajo del otro o mezclados con texto.\n\n"
            "Ejemplo:\n6171234\n48038316651\n2000017817513284"
        )
        self.bulk_input.setMinimumHeight(120)
        iv.addWidget(self.bulk_input)
        ib = QHBoxLayout()
        self.lookup_btn = QPushButton("Buscar y revisar datos")
        self.lookup_btn.clicked.connect(self._lookup)
        clear = QPushButton("Limpiar")
        clear.clicked.connect(self._clear_all)
        ib.addWidget(self.lookup_btn); ib.addWidget(clear); ib.addStretch(1)
        iv.addLayout(ib)
        root.addWidget(input_box)

        resolved_box = QGroupBox("Pedidos encontrados en Epresis")
        rv = QVBoxLayout(resolved_box)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Ingresado", "Guía", "Seller", "Remito", "Guía Agente", "Dirección / localidad"])
        for col in range(5):
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        rv.addWidget(self.table)
        root.addWidget(resolved_box)

        # Automatic data review. The operator normally does not need to type here;
        # fields remain editable only for data that Epresis does not provide.
        middle = QHBoxLayout()
        driver_box = QGroupBox("Datos detectados del chofer")
        df = QFormLayout(driver_box)
        self.surname = QLineEdit(); self.name = QLineEdit(); self.dni = QLineEdit()
        self.birth = QLineEdit(); self.birth.setPlaceholderText("Solo si Epresis no lo tiene: DD/MM/AAAA")
        self.gender = QComboBox(); self.gender.addItems(["", "Masculino", "Femenino"])
        self.phone_prefix = QLineEdit(); self.phone = QLineEdit(); self.email = QLineEdit()
        df.addRow("Apellido:", self.surname); df.addRow("Nombre:", self.name); df.addRow("DNI:", self.dni)
        df.addRow("Fecha de nacimiento:", self.birth); df.addRow("Género:", self.gender)
        phone_row = QWidget(); ph = QHBoxLayout(phone_row); ph.setContentsMargins(0,0,0,0)
        self.phone_prefix.setPlaceholderText("Prefijo"); self.phone.setPlaceholderText("Número")
        ph.addWidget(self.phone_prefix, 1); ph.addWidget(self.phone, 3)
        df.addRow("Teléfono:", phone_row); df.addRow("Email:", self.email)
        middle.addWidget(driver_box, 1)

        incident_box = QGroupBox("Datos automáticos del hecho")
        inf = QFormLayout(incident_box)
        self.date = QDateEdit(QDate.currentDate()); self.date.setCalendarPopup(True); self.date.setDisplayFormat("dd/MM/yyyy")
        cfg = load_config(); dcfg = cfg.get("denuncias") or {}
        self.time = QLineEdit(str(dcfg.get("default_time", "21:00")))
        self.partido = QLineEdit(); self.locality = QLineEdit(); self.street = QLineEdit(); self.number = QLineEdit()
        self.corner = QLineEdit(); self.location_detail = QLineEdit()
        self.violence = QComboBox(); self.violence.addItems(["Sí"]); self.violence.setCurrentText("Sí"); self.violence.setEnabled(False)
        inf.addRow("Fecha:", self.date); inf.addRow("Hora:", self.time); inf.addRow("Partido:", self.partido)
        inf.addRow("Localidad/Barrio:", self.locality); inf.addRow("Calle:", self.street); inf.addRow("Número:", self.number)
        inf.addRow("Esquina más cercana:", self.corner); inf.addRow("Detalle ubicación:", self.location_detail)
        inf.addRow("¿Violencia/daños?:", self.violence)
        middle.addWidget(incident_box, 1)
        root.addLayout(middle)

        narrative_box = QGroupBox("Relato automático")
        nv = QVBoxLayout(narrative_box)
        nr = QHBoxLayout()
        self.random_narrative = QCheckBox("Elegir una redacción aleatoria en cada denuncia"); self.random_narrative.setChecked(True)
        regen = QPushButton("Generar otro relato"); regen.clicked.connect(self._generate_narrative)
        nr.addWidget(self.random_narrative); nr.addWidget(regen); nr.addStretch(1)
        nv.addLayout(nr)
        self.narrative = QTextEdit(); self.narrative.setMinimumHeight(100)
        nv.addWidget(self.narrative); root.addWidget(narrative_box)

        controls = QHBoxLayout()
        self.dry_btn = QPushButton("Probar sin finalizar")
        self.pdf_test_btn = QPushButton("PRUEBA: GENERAR PDF")
        self.pdf_test_btn.setToolTip("Finaliza la denuncia y descarga el PDF, pero NO envía nada por WhatsApp.")
        self.run_btn = QPushButton("HACER DENUNCIA")
        self.run_btn.setMinimumHeight(42)
        self.run_btn.setStyleSheet("font-weight:800;")
        self.dry_btn.clicked.connect(lambda: self._start_from_text("dry"))
        self.pdf_test_btn.clicked.connect(lambda: self._start_from_text("pdf_only"))
        self.run_btn.clicked.connect(lambda: self._start_from_text("full"))
        controls.addStretch(1); controls.addWidget(self.dry_btn); controls.addWidget(self.pdf_test_btn); controls.addWidget(self.run_btn)
        root.addLayout(controls)

        self.logs = QTextEdit(); self.logs.setReadOnly(True); self.logs.setMaximumHeight(120)
        self.logs.setStyleSheet("font-family:Consolas,monospace;font-size:10px;")
        root.addWidget(self.logs)

    def _open_downloads(self):
        try:
            folder = resolve_path(load_config(), 'denuncias_output').resolve()
            folder.mkdir(parents=True, exist_ok=True)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
                raise OSError('No se pudo abrir el Explorador de Windows.')
        except OSError:
            QMessageBox.warning(self, 'Carpeta de denuncias', 'No pude abrir la carpeta de denuncias. Volvé a intentarlo.')

    def _open_messages(self):
        if self._latest_denuncia is None:
            # Recover the latest downloaded complaint after restarting the app.
            # No file picker: this action always refers to one completed complaint.
            try:
                entries = downloaded_reports(resolve_path(load_config(), 'denuncias_output'))
            except OSError:
                entries = []
            if entries:
                self._latest_denuncia = entries[0]
        if not self._latest_denuncia or not self._latest_denuncia.get('sellers'):
            QMessageBox.information(self, 'Mensajes de la denuncia', 'Todavía no hay mensajes guardados para la última denuncia. Estarán disponibles cuando finalices una denuncia desde SmartPost.')
            return
        DenunciasMessagesDialog(self._latest_denuncia, self).exec()

    def _clear_all(self):
        self.bulk_input.clear(); self.shipments = []; self.table.setRowCount(0); self.narrative.clear(); self.logs.clear()

    def _entries(self):
        return [{"query": value, "seller": ""} for value in parse_identifiers(self.bulk_input.toPlainText())]

    def _set_busy(self, busy: bool):
        self.run_btn.setEnabled(not busy); self.dry_btn.setEnabled(not busy); self.pdf_test_btn.setEnabled(not busy); self.lookup_btn.setEnabled(not busy)
        self.messages_btn.setEnabled(not busy)

    def _lookup(self):
        self._pending_submit = None
        self._begin_lookup()

    def _begin_lookup(self):
        entries = self._entries()
        if not entries:
            QMessageBox.warning(self, "Faltan pedidos", "Pegá al menos un número de guía, remito o Guía Agente.")
            return
        self.logs.clear(); self._set_busy(True)
        self.logs.append(f"Detecté {len(entries)} identificador(es). Buscando cada uno como guía, remito o Guía Agente…")
        self.lookup_thread = QThread(self)
        self.lookup_worker = DenunciasLookupWorker(entries)
        self.lookup_worker.moveToThread(self.lookup_thread)
        self.lookup_thread.started.connect(self.lookup_worker.run)
        self.lookup_worker.log_line.connect(self.logs.append)
        self.lookup_worker.finished.connect(self._lookup_finished)
        self.lookup_worker.finished.connect(self.lookup_thread.quit)
        self.lookup_thread.finished.connect(self.lookup_worker.deleteLater)
        self.lookup_thread.finished.connect(self.lookup_thread.deleteLater)
        self.lookup_thread.start()

    def _lookup_finished(self, ok: bool, shipments, driver, detail: str):
        self._set_busy(False)
        if not ok:
            self._pending_submit = None
            ErrorDialog(detail, self).exec(); return
        self.shipments = list(shipments or [])
        self.table.setRowCount(len(self.shipments))
        unresolved = []
        for r, s in enumerate(self.shipments):
            values = [s.get("query",""), s.get("guia",""), s.get("seller",""), s.get("remito",""), s.get("sale_number",""),
                      " - ".join(x for x in [s.get("address",""), s.get("locality","")] if x)]
            for c, value in enumerate(values): self.table.setItem(r,c,QTableWidgetItem(str(value)))
            if not (s.get("guia") and s.get("remito")):
                unresolved.append(str(s.get("query", "")))

        self.surname.setText(str(driver.get("surname", ""))); self.name.setText(str(driver.get("name", "")))
        self.dni.setText(str(driver.get("dni", ""))); self.birth.setText(str(driver.get("birth_date", "")))
        idx = self.gender.findText(str(driver.get("gender", "")))
        if idx >= 0: self.gender.setCurrentIndex(idx)
        self.phone_prefix.setText(str(driver.get("phone_prefix", ""))); self.phone.setText(str(driver.get("phone_number", "")))
        self.email.setText(str(driver.get("email", "")))

        if self.shipments:
            first = self.shipments[0]
            detected_locality = str(first.get("locality", "")).strip()
            if not self.locality.text(): self.locality.setText(detected_locality)
            # Epresis frequently exposes the partido in its Localidad field. Use it
            # as a suggestion, never as a hidden hard-coded value.
            if not self.partido.text(): self.partido.setText(detected_locality)
            if not self.street.text():
                addr = str(first.get("address", "")).strip()
                m = re.match(r"^(.*?)[,\s]+(\d+[A-Za-z]?)$", addr)
                if m:
                    self.street.setText(m.group(1).strip()); self.number.setText(m.group(2))
                else:
                    self.street.setText(addr)
        self._generate_narrative()

        if unresolved:
            self._pending_submit = None
            QMessageBox.warning(
                self, "Pedidos no resueltos",
                "No pude completar estos identificadores en Epresis:\n\n" + "\n".join(unresolved) +
                "\n\nRevisalos antes de iniciar la denuncia."
            )
            return

        if self._pending_submit is not None:
            mode = self._pending_submit
            self._pending_submit = None
            self._submit(mode)

    def _shipments_from_table(self):
        return [dict(s) for s in self.shipments]

    def _generate_narrative(self):
        shipments = self._shipments_from_table()
        lines = [ShipmentLine(str(s.get("seller","")), str(s.get("remito","")), str(s.get("sale_number",""))) for s in shipments if s.get("remito")]
        if not lines:
            self.narrative.setPlainText(""); return
        self.narrative.setPlainText(generate_unknown_circumstances(lines))

    def _missing_required(self):
        missing = []
        shipments = self._shipments_from_table()
        if not shipments: missing.append("pedidos resueltos")
        if any(not s.get("seller") for s in shipments): missing.append("seller de todos los pedidos")
        if any(not s.get("remito") for s in shipments): missing.append("remito de todos los pedidos")
        for label, widget in (("apellido del chofer",self.surname),("nombre del chofer",self.name),("DNI del chofer",self.dni),
                              ("fecha de nacimiento del chofer",self.birth),("partido",self.partido),("calle",self.street),("número",self.number)):
            if not widget.text().strip(): missing.append(label)
        if self.birth.text().strip() and not re.fullmatch(r"\d{2}/\d{2}/\d{4}", self.birth.text().strip()):
            missing.append("fecha de nacimiento válida (DD/MM/AAAA)")
        if not self.gender.currentText(): missing.append("género del chofer")
        if not (self.phone.text().strip() or self.email.text().strip()): missing.append("teléfono o email del chofer")
        if not self.violence.currentText(): missing.append("violencia/daños")
        if not self.narrative.toPlainText().strip(): missing.append("relato")
        return missing

    def _start_from_text(self, mode: str):
        entries = self._entries()
        if not entries:
            QMessageBox.warning(self, "Faltan pedidos", "Pegá los números de los pedidos siniestrados.")
            return
        current_queries = [str(s.get("query", "")) for s in self.shipments]
        desired_queries = [e["query"] for e in entries]
        if not self.shipments or current_queries != desired_queries:
            self._pending_submit = mode
            self._begin_lookup()
            return
        self._submit(mode)

    def _submit(self, mode: str):
        dry_run = mode == "dry"
        send_whatsapp = mode == "full"
        missing = self._missing_required()
        if missing:
            QMessageBox.warning(
                self, "Faltan datos que Epresis no pudo completar",
                "SmartPost encontró los pedidos, pero el formulario oficial exige estos datos:\n\n• " +
                "\n• ".join(missing) +
                "\n\nCompletá únicamente esos datos y volvé a tocar HACER DENUNCIA."
            )
            return
        if mode == "full":
            ans = QMessageBox.question(
                self, "Confirmar denuncia",
                "SmartPost va a completar y FINALIZAR la denuncia oficial. Cuando aparezca el CAPTCHA, resolvelo vos; después continuará automáticamente y enviará el PDF por WhatsApp. ¿Continuar?"
            )
            if ans != QMessageBox.Yes: return
        elif mode == "pdf_only":
            ans = QMessageBox.question(
                self, "Prueba con PDF",
                "Esta prueba FINALIZA la denuncia oficial y descarga el PDF en tu PC, pero se detiene antes de WhatsApp. ¿Continuar?"
            )
            if ans != QMessageBox.Yes: return
        shipments = self._shipments_from_table()
        driver = {
            "surname":self.surname.text().strip(), "name":self.name.text().strip(), "dni":self.dni.text().strip(),
            "birth_date":self.birth.text().strip(), "gender":self.gender.currentText(),
            "phone_prefix":self.phone_prefix.text().strip(), "phone_number":self.phone.text().strip(), "email":self.email.text().strip(),
        }
        qd = self.date.date()
        incident = {
            "date":f"{qd.day():02d}/{qd.month():02d}/{qd.year():04d}", "time":self.time.text().strip(),
            "partido":self.partido.text().strip(), "locality":self.locality.text().strip(),
            "street":self.street.text().strip(), "number":self.number.text().strip(), "corner":self.corner.text().strip(),
            "location_detail":self.location_detail.text().strip(), "violence":self.violence.currentText(),
        }
        if self.random_narrative.isChecked():
            self._generate_narrative()
        narrative = self.narrative.toPlainText().strip()
        self._set_busy(True); self.logs.clear()
        self.submit_thread = QThread(self)
        self.submit_worker = DenunciasSubmitWorker(shipments, driver, incident, narrative, dry_run, send_whatsapp=send_whatsapp)
        self.submit_worker.moveToThread(self.submit_thread)
        self.submit_thread.started.connect(self.submit_worker.run)
        self.submit_worker.log_line.connect(self.logs.append)
        self.submit_worker.finished.connect(self._submit_finished)
        self.submit_worker.finished.connect(self.submit_thread.quit)
        self.submit_thread.finished.connect(self.submit_worker.deleteLater)
        self.submit_thread.finished.connect(self.submit_thread.deleteLater)
        self.submit_thread.start()

    def _submit_finished(self, ok: bool, summary, detail: str):
        self._set_busy(False)
        summary = summary or {}
        if summary.get('denuncia') and not summary.get('dry_run'):
            self._latest_denuncia = deepcopy(summary['denuncia'])
        if not ok:
            ErrorDialog(detail, self).exec(); return
        if summary.get("dry_run"):
            QMessageBox.information(self, "Prueba terminada", "La prueba terminó sin finalizar la denuncia ni enviar WhatsApp.")
        elif not summary.get("send_whatsapp", True):
            pdf = summary.get("pdf", "")
            QMessageBox.information(
                self,
                "PDF de prueba generado",
                f"La denuncia se finalizó y el PDF quedó descargado en tu PC:\n\n{pdf}\n\nNo se envió nada por WhatsApp.",
            )
        else:
            QMessageBox.information(
                self,
                "Denuncia finalizada",
                f"PDF: {summary.get('pdf','')}\n\nSe procesaron los envíos de WhatsApp.",
            )
