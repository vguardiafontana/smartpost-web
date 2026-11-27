"""ABM de sellers en Reportes Desktop."""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QPushButton,
    QLineEdit, QCheckBox, QLabel, QMessageBox, QDialogButtonBox, QWidget)
from app.reportes import desktop_sellers

DAYS = ('Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom')


class SellerEditor(QDialog):
    def __init__(self, seller=None, parent=None):
        super().__init__(parent)
        self.original = seller['seller'] if seller else None
        self.setWindowTitle('Editar seller' if seller else 'Agregar seller')
        self.resize(540, 270)
        data = seller or {}
        layout = QVBoxLayout(self)
        form = QFormLayout(); layout.addLayout(form)
        self.name = QLineEdit(data.get('seller', '')); form.addRow('Nombre del seller', self.name)
        self.client = QLineEdit(data.get('client', '')); form.addRow('Cliente exacto en Precis', self.client)
        self.group = QLineEdit(data.get('group', '')); form.addRow('Grupo exacto de WhatsApp', self.group)
        row = QWidget(); days = QHBoxLayout(row); days.setContentsMargins(0, 0, 0, 0)
        self.days = []
        for i, day in enumerate(DAYS):
            box = QCheckBox(day); box.setChecked(i in data.get('days', range(5))); days.addWidget(box); self.days.append(box)
        form.addRow('Días de reporte', row)
        self.enabled = QCheckBox('Seller habilitado'); self.enabled.setChecked(data.get('enabled', True)); layout.addWidget(self.enabled)
        note = QLabel('El grupo de WhatsApp es necesario para el flujo actual de Reportes. Los días se aplican a la fecha seleccionada.'); note.setWordWrap(True); layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText('Guardar'); buttons.button(QDialogButtonBox.Cancel).setText('Cancelar')
        buttons.accepted.connect(self._save); buttons.rejected.connect(self.reject); layout.addWidget(buttons)

    def _save(self):
        try:
            desktop_sellers.update_seller(self.original, self.name.text(), self.client.text(),
                [i for i, box in enumerate(self.days) if box.isChecked()], self.group.text(), self.enabled.isChecked())
        except Exception as exc:
            QMessageBox.warning(self, 'No se pudo guardar', str(exc)); return
        self.accept()


class ReportSellersDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Administrar sellers — Reportes'); self.resize(840, 460)
        layout = QVBoxLayout(self)
        note = QLabel('Configuración local de Desktop. No modifica los sellers de otros módulos ni la configuración de Web.'); note.setWordWrap(True); layout.addWidget(note)
        self.table = QTableWidget(0, 5); self.table.setHorizontalHeaderLabels(['Seller', 'Cliente en Precis', 'Días', 'Grupo WhatsApp', 'Estado'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows); self.table.setSelectionMode(QAbstractItemView.SingleSelection); self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); layout.addWidget(self.table)
        actions = QHBoxLayout(); layout.addLayout(actions)
        for text, slot in [('+ Agregar seller', self._add), ('Editar', self._edit), ('Eliminar', self._delete)]:
            button = QPushButton(text); button.clicked.connect(slot); actions.addWidget(button)
        actions.addStretch(); close = QPushButton('Cerrar'); close.clicked.connect(self.accept); actions.addWidget(close)
        self.table.cellDoubleClicked.connect(lambda *_: self._edit())
        self._reload()

    def _reload(self):
        self.rows = desktop_sellers.list_sellers(); self.table.setRowCount(len(self.rows))
        for r, seller in enumerate(self.rows):
            values = (seller['seller'], seller['client'], ', '.join(DAYS[i] for i in sorted(seller['days'])), seller['group'], 'Activo' if seller['enabled'] else 'Inactivo')
            for c, value in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(str(value)))

    def _selected(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, 'Seller', 'Seleccioná un seller de la tabla.'); return None
        return self.rows[row]

    def _add(self):
        if SellerEditor(parent=self).exec(): self._reload()

    def _edit(self):
        seller = self._selected()
        if seller and SellerEditor(seller, self).exec(): self._reload()

    def _delete(self):
        seller = self._selected()
        if not seller: return
        if QMessageBox.question(self, 'Eliminar seller', f"¿Eliminar {seller['seller']} de Reportes Desktop?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes: return
        try:
            desktop_sellers.delete_seller(seller['seller']); self._reload()
        except Exception as exc:
            QMessageBox.warning(self, 'No se pudo eliminar', str(exc))
