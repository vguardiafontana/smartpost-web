from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget, QFormLayout,
    QLineEdit, QTextEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QCheckBox, QPushButton, QMessageBox, QLabel, QSpinBox
)

from app.core.config import load_config, save_config
from app.descarga.credentials import get_credentials, save_credentials


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuración de SmartPost")
        self.resize(850, 620)
        self.cfg = load_config()
        root = QVBoxLayout(self)
        tabs = QTabWidget()
        root.addWidget(tabs)

        # Epresis
        ep = QWidget(); ep_form = QFormLayout(ep)
        user, _ = get_credentials()
        self.user = QLineEdit(user or "")
        self.password = QLineEdit(); self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("Dejar vacío para conservar la contraseña actual")
        ep_form.addRow("Usuario de Epresis:", self.user)
        ep_form.addRow("Contraseña:", self.password)
        note = QLabel("La contraseña se guarda de forma segura mediante el Administrador de credenciales de Windows.")
        note.setWordWrap(True)
        ep_form.addRow(note)
        tabs.addTab(ep, "Epresis")

        # WhatsApp
        wa = QWidget(); wa_form = QFormLayout(wa)
        self.message = QLineEdit(self.cfg.get("whatsapp", {}).get("attachment_caption", "Buenas noches, adjunto el reporte del día {date}."))
        wa_form.addRow("Mensaje:", self.message)
        hint = QLabel("Usá {date} donde deba aparecer la fecha seleccionada, por ejemplo 18/09.")
        hint.setWordWrap(True); wa_form.addRow(hint)
        tabs.addTab(wa, "WhatsApp")

        # Visitas
        visits = QWidget(); vv = QVBoxLayout(visits)
        visits_cfg = self.cfg.get("visitas") or {}
        vf = QFormLayout()
        self.visits_enabled = QCheckBox("Generar y enviar el Excel de VISITAS")
        self.visits_enabled.setChecked(bool(visits_cfg.get("enabled", True)))
        self.visits_group = QLineEdit(str(visits_cfg.get("whatsapp_group", "CONSULTAS / Operación nocturna")))
        self.visits_message = QLineEdit(str(visits_cfg.get("whatsapp_message", "")))
        self.visits_message.setPlaceholderText("Vacío = enviar solamente el archivo")
        self.visits_filename = QLineEdit(str(visits_cfg.get("filename", "VISITAS {date_short}.xlsx")))
        vf.addRow(self.visits_enabled)
        vf.addRow("Grupo de WhatsApp:", self.visits_group)
        vf.addRow("Mensaje (opcional):", self.visits_message)
        vf.addRow("Nombre del archivo:", self.visits_filename)
        visits_hint = QLabel("El mensaje puede quedar vacío. En el nombre podés usar {date_short}, por ejemplo 21-09-26.")
        visits_hint.setWordWrap(True); vf.addRow(visits_hint)
        vv.addLayout(vf)

        vv.addWidget(QLabel("Estados incluidos en VISITAS:"))
        states = visits_cfg.get("estados") or []
        self.visits_states = QTableWidget(len(states), 2)
        self.visits_states.setHorizontalHeaderLabels(["ID", "Nombre"])
        self.visits_states.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.visits_states.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.visits_states.verticalHeader().setVisible(False)
        for row, item in enumerate(states):
            self.visits_states.setItem(row, 0, QTableWidgetItem(str(item.get("id", ""))))
            self.visits_states.setItem(row, 1, QTableWidgetItem(str(item.get("name", ""))))
        vv.addWidget(self.visits_states)
        state_buttons = QHBoxLayout()
        add_state = QPushButton("Agregar estado")
        remove_state = QPushButton("Quitar seleccionado")
        add_state.clicked.connect(self._add_visit_state)
        remove_state.clicked.connect(self._remove_visit_state)
        state_buttons.addWidget(add_state); state_buttons.addWidget(remove_state); state_buttons.addStretch(1)
        vv.addLayout(state_buttons)
        tabs.addTab(visits, "Visitas")

        # Denuncias
        den = QWidget(); dv = QVBoxLayout(den)
        dcfg = self.cfg.get("denuncias") or {}
        df = QFormLayout()
        self.den_enabled = QCheckBox("Habilitar módulo de Denuncias")
        self.den_enabled.setChecked(bool(dcfg.get("enabled", True)))
        self.den_group = QLineEdit(str(dcfg.get("whatsapp_group", "CONSULTAS / Operación nocturna")))
        self.den_time = QLineEdit(str(dcfg.get("default_time", "21:00")))
        self.den_url = QLineEdit(str(dcfg.get("gba_url", "https://seguridad.gba.gob.ar/#/robo-otros")))
        self.den_dist_path = QLineEdit(str(dcfg.get("distributor_search_path", "/distribuidores/lista-distribuidores")))
        df.addRow(self.den_enabled)
        df.addRow("Grupo general (PDF sin mensaje):", self.den_group)
        df.addRow("Hora predeterminada:", self.den_time)
        df.addRow("URL denuncia GBA:", self.den_url)
        df.addRow("Ruta búsqueda Distribuidores:", self.den_dist_path)
        dv.addLayout(df)
        dv.addWidget(QLabel("Mensaje para un envío (usar {remito}):"))
        self.den_singular = QTextEdit(str(dcfg.get("seller_message_singular", ""))); self.den_singular.setMaximumHeight(90); dv.addWidget(self.den_singular)
        dv.addWidget(QLabel("Mensaje para varios envíos (usar {remitos}):"))
        self.den_plural = QTextEdit(str(dcfg.get("seller_message_plural", ""))); self.den_plural.setMaximumHeight(110); dv.addWidget(self.den_plural)
        dv.addWidget(QLabel("Grupos adicionales para sellers que no participan de Reportes:"))
        extra_groups = dcfg.get("seller_groups") or []
        self.den_groups = QTableWidget(len(extra_groups), 2)
        self.den_groups.setHorizontalHeaderLabels(["Seller", "Grupo de WhatsApp"])
        self.den_groups.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.den_groups.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.den_groups.verticalHeader().setVisible(False)
        for row, item in enumerate(extra_groups):
            self.den_groups.setItem(row, 0, QTableWidgetItem(str(item.get("seller", ""))))
            self.den_groups.setItem(row, 1, QTableWidgetItem(str(item.get("whatsapp_group", ""))))
        dv.addWidget(self.den_groups)
        den_group_buttons = QHBoxLayout()
        den_add_group = QPushButton("Agregar seller")
        den_remove_group = QPushButton("Quitar seleccionado")
        den_add_group.clicked.connect(self._add_den_group)
        den_remove_group.clicked.connect(self._remove_den_group)
        den_group_buttons.addWidget(den_add_group); den_group_buttons.addWidget(den_remove_group); den_group_buttons.addStretch(1)
        dv.addLayout(den_group_buttons)
        den_note = QLabel("Los sellers que ya existen en Reportes reutilizan su grupo. Esta tabla sirve para otros sellers de denuncias. El CAPTCHA no se automatiza: SmartPost espera a que lo completes y continúa.")
        den_note.setWordWrap(True); dv.addWidget(den_note)
        tabs.addTab(den, "Denuncias")

        # Sellers
        sw = QWidget(); sv = QVBoxLayout(sw)
        self.table = QTableWidget(len(self.cfg["sellers"]), 3)
        self.table.setHorizontalHeaderLabels(["Activo", "Seller", "Grupo de WhatsApp"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        for row, seller in enumerate(self.cfg["sellers"]):
            active = QTableWidgetItem(); active.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            active.setCheckState(Qt.Checked if seller.get("enabled", True) else Qt.Unchecked)
            self.table.setItem(row, 0, active)
            name = QTableWidgetItem(str(seller["seller"])); name.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(row, 1, name)
            self.table.setItem(row, 2, QTableWidgetItem(str(seller.get("whatsapp_group", ""))))
        sv.addWidget(self.table)
        tabs.addTab(sw, "Sellers y grupos")

        # General
        general = QWidget(); gf = QFormLayout(general)
        self.retention = QSpinBox(); self.retention.setRange(0, 3650); self.retention.setValue(int(self.cfg.get("app", {}).get("raw_retention_days", 30)))
        gf.addRow("Días de histórico de crudos:", self.retention)
        tabs.addTab(general, "General")

        buttons = QHBoxLayout(); buttons.addStretch(1)
        cancel = QPushButton("Cancelar"); save = QPushButton("Guardar")
        cancel.clicked.connect(self.reject); save.clicked.connect(self._save)
        buttons.addWidget(cancel); buttons.addWidget(save); root.addLayout(buttons)

    def _save(self):
        message = self.message.text().strip()
        if "{date}" not in message:
            QMessageBox.warning(self, "Mensaje inválido", "El mensaje debe incluir {date} para usar la fecha seleccionada.")
            return
        user = self.user.text().strip()
        password = self.password.text()
        old_user, old_password = get_credentials()
        if not user:
            QMessageBox.warning(self, "Falta usuario", "Ingresá el usuario de Epresis.")
            return
        if password:
            save_credentials(user, password)
        elif user != (old_user or ""):
            if not old_password:
                QMessageBox.warning(self, "Falta contraseña", "Ingresá la contraseña para el nuevo usuario de Epresis.")
                return
            save_credentials(user, old_password)

        visits_states = []
        seen_ids = set()
        for row in range(self.visits_states.rowCount()):
            id_item = self.visits_states.item(row, 0)
            name_item = self.visits_states.item(row, 1)
            raw_id = (id_item.text() if id_item else "").strip()
            state_name = (name_item.text() if name_item else "").strip()
            if not raw_id and not state_name:
                continue
            try:
                state_id = int(raw_id)
            except ValueError:
                QMessageBox.warning(self, "Estado inválido", f"El ID de estado '{raw_id}' no es numérico.")
                return
            if state_id in seen_ids:
                QMessageBox.warning(self, "Estado duplicado", f"El ID {state_id} está repetido en Visitas.")
                return
            seen_ids.add(state_id)
            visits_states.append({"id": state_id, "name": state_name or f"Estado {state_id}"})

        if self.visits_enabled.isChecked() and not visits_states:
            QMessageBox.warning(self, "Faltan estados", "Visitas está habilitado pero no tiene estados configurados.")
            return
        if self.visits_enabled.isChecked() and not self.visits_group.text().strip():
            QMessageBox.warning(self, "Falta grupo", "Ingresá el grupo de WhatsApp para Visitas.")
            return
        visits_filename = self.visits_filename.text().strip()
        if not visits_filename:
            QMessageBox.warning(self, "Falta nombre", "Ingresá el nombre del archivo de Visitas.")
            return

        if self.den_enabled.isChecked():
            if not self.den_group.text().strip():
                QMessageBox.warning(self, "Falta grupo", "Ingresá el grupo general de WhatsApp para Denuncias.")
                return
            if "{remito}" not in self.den_singular.toPlainText():
                QMessageBox.warning(self, "Mensaje inválido", "El mensaje singular de Denuncias debe incluir {remito}.")
                return
            if "{remitos}" not in self.den_plural.toPlainText():
                QMessageBox.warning(self, "Mensaje inválido", "El mensaje plural de Denuncias debe incluir {remitos}.")
                return

        den_groups = []
        seen_den_sellers = set()
        for row in range(self.den_groups.rowCount()):
            seller_item = self.den_groups.item(row, 0)
            group_item = self.den_groups.item(row, 1)
            seller_name = (seller_item.text() if seller_item else "").strip()
            group_name = (group_item.text() if group_item else "").strip()
            if not seller_name and not group_name:
                continue
            if not seller_name or not group_name:
                QMessageBox.warning(self, "Grupo incompleto", "Cada grupo adicional de Denuncias necesita seller y nombre de grupo.")
                return
            key = seller_name.casefold()
            if key in seen_den_sellers:
                QMessageBox.warning(self, "Seller duplicado", f"El seller '{seller_name}' está repetido en Denuncias.")
                return
            seen_den_sellers.add(key)
            den_groups.append({"seller": seller_name, "whatsapp_group": group_name})

        self.cfg["denuncias"] = {
            **(self.cfg.get("denuncias") or {}),
            "enabled": self.den_enabled.isChecked(),
            "whatsapp_group": self.den_group.text().strip(),
            "default_time": self.den_time.text().strip() or "21:00",
            "gba_url": self.den_url.text().strip(),
            "distributor_search_path": self.den_dist_path.text().strip() or "/distribuidores/lista-distribuidores",
            "seller_message_singular": self.den_singular.toPlainText().strip(),
            "seller_message_plural": self.den_plural.toPlainText().strip(),
            "seller_groups": den_groups,
        }

        self.cfg["whatsapp"]["attachment_caption"] = message
        self.cfg["visitas"] = {
            **(self.cfg.get("visitas") or {}),
            "enabled": self.visits_enabled.isChecked(),
            "whatsapp_group": self.visits_group.text().strip(),
            "whatsapp_message": self.visits_message.text(),
            "filename": visits_filename,
            "estados": visits_states,
        }
        self.cfg["app"]["raw_retention_days"] = self.retention.value()
        for row, seller in enumerate(self.cfg["sellers"]):
            seller["enabled"] = self.table.item(row, 0).checkState() == Qt.Checked
            seller["whatsapp_group"] = self.table.item(row, 2).text().strip()
        self.cfg["app"]["first_run_complete"] = True
        save_config(self.cfg)
        self.accept()

    def _add_den_group(self):
        row = self.den_groups.rowCount()
        self.den_groups.insertRow(row)
        self.den_groups.setItem(row, 0, QTableWidgetItem(""))
        self.den_groups.setItem(row, 1, QTableWidgetItem(""))
        self.den_groups.setCurrentCell(row, 0)

    def _remove_den_group(self):
        row = self.den_groups.currentRow()
        if row >= 0:
            self.den_groups.removeRow(row)

    def _add_visit_state(self):
        row = self.visits_states.rowCount()
        self.visits_states.insertRow(row)
        self.visits_states.setItem(row, 0, QTableWidgetItem(""))
        self.visits_states.setItem(row, 1, QTableWidgetItem(""))
        self.visits_states.setCurrentCell(row, 0)

    def _remove_visit_state(self):
        row = self.visits_states.currentRow()
        if row >= 0:
            self.visits_states.removeRow(row)
