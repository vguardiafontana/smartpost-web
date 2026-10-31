from __future__ import annotations

from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPlainTextEdit, QPushButton,
)


class DenunciasMessagesDialog(QDialog):
    """Messages for one completed complaint, independent of the PDF folder."""

    def __init__(self, denuncia, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Mensajes de la última denuncia')
        self.resize(760, 480)
        layout = QVBoxLayout(self)
        description = QLabel('Denuncia: ' + str(denuncia.get('filename') or 'Última denuncia finalizada'))
        description.setWordWrap(True)
        layout.addWidget(description)
        layout.addWidget(QLabel('Elegí el seller para ver y copiar su mensaje.'))
        self.sellers = QComboBox()
        for seller in denuncia.get('sellers') or []:
            self.sellers.addItem(str(seller['seller']), str(seller['message']))
        layout.addWidget(self.sellers)
        self.message = QPlainTextEdit(); self.message.setReadOnly(True)
        layout.addWidget(self.message, 1)
        actions = QHBoxLayout()
        self.copy_btn = QPushButton('Copiar mensaje'); self.copy_btn.setProperty('primary', True)
        self.copy_btn.clicked.connect(self._copy_message)
        close = QPushButton('Cerrar'); close.clicked.connect(self.accept)
        actions.addWidget(self.copy_btn); actions.addStretch(); actions.addWidget(close)
        layout.addLayout(actions)
        self.sellers.currentIndexChanged.connect(self._select_seller)
        self._select_seller()

    def _select_seller(self, *_):
        self.message.setPlainText(self.sellers.currentData() or '')
        self.copy_btn.setEnabled(bool(self.sellers.currentData()))
        self.copy_btn.setText('Copiar mensaje')

    def _copy_message(self):
        QApplication.clipboard().setText(self.message.toPlainText())
        self.copy_btn.setText('Mensaje copiado')
