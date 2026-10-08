from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWizard, QWizardPage, QVBoxLayout, QLabel, QFormLayout, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox
)

from app.core.config import load_config, save_config
from app.core.system_checks import has_excel
from app.descarga.credentials import get_credentials, save_credentials


class InitialSetupWizard(QWizard):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bienvenido a SmartPost")
        self.resize(820, 600)
        self.cfg = load_config()

        intro = QWizardPage(); intro.setTitle("Configuración inicial")
        il = QVBoxLayout(intro)
        il.addWidget(QLabel("Este asistente configura SmartPost sin editar archivos manualmente."))
        excel_text = "✓ Microsoft Excel detectado." if has_excel() else "⚠ No se detectó Microsoft Excel de escritorio. SmartPost lo necesita para generar los reportes finales."
        lbl = QLabel(excel_text); lbl.setWordWrap(True); il.addWidget(lbl)
        il.addWidget(QLabel("Después vas a poder cambiar todo desde el botón Configuración."))
        self.addPage(intro)

        ep = QWizardPage(); ep.setTitle("Acceso a Epresis")
        ef = QFormLayout(ep)
        current_user, _ = get_credentials()
        self.user = QLineEdit(current_user or "")
        self.password = QLineEdit(); self.password.setEchoMode(QLineEdit.Password)
        ef.addRow("Usuario:", self.user); ef.addRow("Contraseña:", self.password)
        note = QLabel("La contraseña queda guardada en el Administrador de credenciales de Windows."); note.setWordWrap(True); ef.addRow(note)
        self.addPage(ep)

        sellers = QWizardPage(); sellers.setTitle("Grupos de WhatsApp")
        sl = QVBoxLayout(sellers)
        sl.addWidget(QLabel("Indicá el nombre exacto del grupo de WhatsApp para cada seller. Podés completar o corregir esto más tarde."))
        self.table = QTableWidget(len(self.cfg["sellers"]), 2)
        self.table.setHorizontalHeaderLabels(["Seller", "Grupo de WhatsApp"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        for row, s in enumerate(self.cfg["sellers"]):
            item = QTableWidgetItem(str(s["seller"])); item.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(row, 0, item)
            self.table.setItem(row, 1, QTableWidgetItem(str(s.get("whatsapp_group", ""))))
        sl.addWidget(self.table)
        visits_cfg = self.cfg.get("visitas") or {}
        visits_form = QFormLayout()
        self.visits_group = QLineEdit(str(visits_cfg.get("whatsapp_group", "CONSULTAS / Operación nocturna")))
        visits_form.addRow("Grupo para VISITAS:", self.visits_group)
        visits_note = QLabel("VISITAS se envía como archivo solamente, sin mensaje. Esto se puede cambiar después desde Configuración.")
        visits_note.setWordWrap(True); visits_form.addRow(visits_note)
        sl.addLayout(visits_form)
        self.addPage(sellers)

    def accept(self):
        user = self.user.text().strip()
        password = self.password.text()
        existing_user, existing_password = get_credentials()
        if not user:
            QMessageBox.warning(self, "Falta usuario", "Ingresá el usuario de Epresis.")
            return
        if password:
            save_credentials(user, password)
        elif not existing_password or user != existing_user:
            QMessageBox.warning(self, "Falta contraseña", "Ingresá la contraseña de Epresis.")
            return
        for row, seller in enumerate(self.cfg["sellers"]):
            seller["whatsapp_group"] = self.table.item(row, 1).text().strip()
        if self.cfg.get("visitas", {}).get("enabled", True):
            group = self.visits_group.text().strip()
            if not group:
                QMessageBox.warning(self, "Falta grupo", "Ingresá el grupo de WhatsApp para VISITAS.")
                return
            self.cfg["visitas"]["whatsapp_group"] = group
        self.cfg["app"]["first_run_complete"] = True
        save_config(self.cfg)
        super().accept()
