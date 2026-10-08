from __future__ import annotations

from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QTextEdit, QHBoxLayout


def friendly_error(detail: str) -> str:
    d = (detail or "").lower()
    if any(x in d for x in ("429", "timeout", "timed out", "net::", "connection", "conectar")):
        return "No se pudo completar la conexión con Epresis. Revisá tu conexión a Internet y volvé a intentar."
    if any(x in d for x in ("excel.application", "dispatch", "com", "microsoft excel")):
        return "No se pudo usar Microsoft Excel. Verificá que Excel de escritorio esté instalado y abra normalmente."
    if "faltan grupos" in d or "whatsapp_group" in d:
        return "Faltan grupos de WhatsApp por configurar. Abrí Configuración y completá los grupos pendientes."
    if "whatsapp web no quedó" in d or "qr" in d or "logueado" in d:
        return "WhatsApp Web no está vinculado. Usá el botón “Vincular WhatsApp” y escaneá el código QR."
    if "credencial" in d or "usuario" in d and "epresis" in d:
        return "No se pudo iniciar sesión en Epresis. Revisá el usuario y la contraseña en Configuración."
    if "template_reporte" in d or "prompt_maestro" in d:
        return "Los archivos internos del reporte no coinciden con la versión esperada. Reinstalá SmartPost o contactá al responsable técnico."
    return "SmartPost no pudo completar el proceso. Podés ver el detalle técnico para identificar el paso que falló."


class ErrorDialog(QDialog):
    def __init__(self, detail: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SmartPost - Error")
        self.resize(620, 260)
        layout = QVBoxLayout(self)
        title = QLabel("⚠  No se pudo completar la ejecución")
        title.setStyleSheet("font-size: 17px; font-weight: 700;")
        layout.addWidget(title)
        msg = QLabel(friendly_error(detail))
        msg.setWordWrap(True)
        layout.addWidget(msg)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlainText(detail or "Sin detalle técnico disponible.")
        self.details.setVisible(False)
        layout.addWidget(self.details)
        buttons = QHBoxLayout()
        toggle = QPushButton("Ver detalle técnico")
        close = QPushButton("Cerrar")
        toggle.clicked.connect(lambda: self._toggle(toggle))
        close.clicked.connect(self.accept)
        buttons.addWidget(toggle)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _toggle(self, button: QPushButton) -> None:
        visible = not self.details.isVisible()
        self.details.setVisible(visible)
        button.setText("Ocultar detalle técnico" if visible else "Ver detalle técnico")
        self.resize(700, 480 if visible else 260)
