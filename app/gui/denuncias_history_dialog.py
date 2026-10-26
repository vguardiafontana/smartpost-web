from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget, QComboBox, QPlainTextEdit

from app.denuncias.history import downloaded_reports


class DenunciasHistoryDialog(QDialog):
    def __init__(self, folder, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Denuncias descargadas y mensajes por seller")
        self.resize(850, 620)
        self.entries = downloaded_reports(folder)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Elegí una denuncia para abrir el PDF o copiar el mensaje de cada seller."))
        self.files = QListWidget()
        for entry in self.entries:
            self.files.addItem(entry["filename"])
        layout.addWidget(self.files)
        actions = QHBoxLayout()
        self.open_btn = QPushButton("Abrir PDF")
        self.open_btn.clicked.connect(self._open_pdf)
        folder_btn = QPushButton("Abrir carpeta de denuncias")
        folder_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))))
        actions.addWidget(self.open_btn); actions.addWidget(folder_btn); layout.addLayout(actions)
        self.sellers = QComboBox(); layout.addWidget(self.sellers)
        self.message = QPlainTextEdit(); self.message.setReadOnly(True); layout.addWidget(self.message)
        self.copy_btn = QPushButton("Copiar mensaje")
        self.copy_btn.clicked.connect(self._copy_message); layout.addWidget(self.copy_btn)
        close = QPushButton("Cerrar"); close.clicked.connect(self.accept); layout.addWidget(close)
        self.files.currentRowChanged.connect(self._select_pdf)
        self.sellers.currentIndexChanged.connect(self._select_seller)
        self.open_btn.setEnabled(bool(self.entries))
        self.copy_btn.setEnabled(False)
        if self.entries:
            self.files.setCurrentRow(0)
        else:
            self.message.setPlainText("Todavía no hay denuncias descargadas en esta carpeta.")

    def _select_pdf(self, index):
        self.sellers.clear()
        if index < 0:
            return
        for seller in self.entries[index]["sellers"]:
            self.sellers.addItem(seller["seller"], seller["message"])
        if not self.sellers.count():
            self.message.setPlainText("Este PDF anterior no tiene sellers y remitos guardados. Podés abrirlo desde el botón Abrir PDF.")
            self.copy_btn.setEnabled(False)

    def _select_seller(self, index):
        self.message.setPlainText(self.sellers.currentData() or "")
        self.copy_btn.setEnabled(bool(self.sellers.currentData()))
        self.copy_btn.setText("Copiar mensaje")

    def _open_pdf(self):
        index = self.files.currentRow()
        if index >= 0:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.entries[index]["pdf"]))

    def _copy_message(self):
        QApplication.clipboard().setText(self.message.toPlainText())
        self.copy_btn.setText("Mensaje copiado")
