from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QDate, QThread, QTimer, QUrl, QSize
from PySide6.QtGui import QColor, QBrush, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QDateEdit,
    QPushButton, QTextEdit, QProgressBar, QGroupBox, QGridLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QStackedWidget,
    QFrame, QSizePolicy, QScrollArea, QApplication
)

from app.core.config import load_config, resolve_path
from app.core.runtime_paths import resource_path
from app.core.system_checks import has_excel
from app.gui.error_dialog import ErrorDialog
from app.gui.settings_dialog import SettingsDialog
from app.gui.setup_wizard import InitialSetupWizard
from app.gui.workers import PipelineWorker, WhatsAppLoginWorker, WhatsAppArchiveToggleWorker
from app.gui.denuncias_page import DenunciasPage
from app.gui.cambio_estado_v2_page import CambioEstadoV2Page
from app.gui.busqueda_guias_page import BusquedaGuiasPage
from app.gui.visitas_fotos_page import VisitasFotosPage


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        from app.gui.theme import apply_theme
        apply_theme(QApplication.instance())
        self.setWindowTitle("SmartPost")
        # Arranque cómodo, pero la ventana queda completamente redimensionable.
        # El mínimo es deliberadamente bajo; las páginas extensas usan scroll.
        self.resize(1240, 820)
        self.setMinimumSize(720, 520)
        icon = resource_path("assets/smartpost.ico")
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self.thread = None
        self.worker = None
        self.chat_thread = None
        self.chat_worker = None
        self._build_ui()
        QTimer.singleShot(100, self._first_run_if_needed)

    def _build_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        outer = QHBoxLayout(central); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        rail = QFrame(); rail.setObjectName("rail"); rail.setFixedWidth(58)
        rail_layout = QVBoxLayout(rail); rail_layout.setContentsMargins(6, 18, 6, 16)
        monogram = QLabel("S"); monogram.setAlignment(Qt.AlignCenter)
        monogram.setStyleSheet("font-size:26px;font-weight:800;color:white;")
        rail_layout.addWidget(monogram); rail_layout.addSpacing(26)
        home = QPushButton(); home.setIcon(QIcon(str(resource_path('assets/icons/home.svg')))); home.setIconSize(QSize(22, 22)); home.setObjectName("railButton"); home.setToolTip("Inicio"); home.setAccessibleName("Inicio")
        home.clicked.connect(lambda: self.stack.setCurrentWidget(self.home_page)); rail_layout.addWidget(home)
        rail_layout.addStretch()
        settings = QPushButton(); settings.setIcon(QIcon(str(resource_path('assets/icons/settings.svg')))); settings.setIconSize(QSize(22, 22)); settings.setObjectName("railButton"); settings.setToolTip("Configuración"); settings.setAccessibleName("Configuración")
        settings.clicked.connect(self._settings); rail_layout.addWidget(settings)
        outer.addWidget(rail)
        sidebar = QFrame(); sidebar.setObjectName("sidebar"); sidebar.setFixedWidth(190)
        side = QVBoxLayout(sidebar); side.setContentsMargins(16, 24, 16, 18); side.setSpacing(8)
        brand = QLabel("SmartPost"); brand.setObjectName("sidebarBrand"); side.addWidget(brand)
        label = QLabel("TU ESPACIO DE TRABAJO"); label.setObjectName("eyebrow"); side.addWidget(label)
        side.addSpacing(28)
        self.nav_buttons = {}
        for key, text in (("home_page", "Inicio"), ("cambio_estado_v2_page", "Cambio de estado v2"), ("reports_page", "Reportes y Visitas"),
                          ("denuncias_page", "Denuncias"), ("busqueda_guias_page", "Búsqueda de guías"),
                          ("visitas_fotos_page", "Visitas sin foto")):
            button = QPushButton(text); button.setObjectName("navButton"); button.setCheckable(True)
            button.clicked.connect(lambda checked=False, key=key: self._navigate(key))
            self.nav_buttons[key] = button; side.addWidget(button)
        side.addStretch()
        foot = QLabel("DESKTOP\nTodo en un solo lugar"); foot.setStyleSheet("color:#a5a7ba;font-size:11px;")
        side.addWidget(foot); outer.addWidget(sidebar)
        workspace = QWidget(); workspace.setObjectName("workspace")
        root = QVBoxLayout(workspace); root.setContentsMargins(24, 20, 24, 16); root.setSpacing(20)
        outer.addWidget(workspace, 1)
        header = QHBoxLayout()
        caption = QLabel("OPERACIONES / SMARTPOST"); caption.setObjectName("eyebrow"); header.addWidget(caption)
        header.addStretch(1)
        self.settings_btn = QPushButton("Configuración"); self.settings_btn.clicked.connect(self._settings)
        self.login_btn = QPushButton("Vincular WhatsApp"); self.login_btn.clicked.connect(self._login_whatsapp)
        header.addWidget(self.login_btn); header.addWidget(self.settings_btn); root.addLayout(header)

        self.stack = QStackedWidget(); root.addWidget(self.stack, 1)
        self.home_page = self._build_home_page(); self.stack.addWidget(self.home_page)
        self.reports_page = self._build_reports_page(); self.stack.addWidget(self.reports_page)
        self.cambio_estado_v2_page = CambioEstadoV2Page()
        self.cambio_estado_v2_page.back_requested.connect(lambda: self.stack.setCurrentWidget(self.home_page))
        self.stack.addWidget(self.cambio_estado_v2_page)
        self.denuncias_page = DenunciasPage(); self.denuncias_page.back_requested.connect(lambda: self.stack.setCurrentWidget(self.home_page))
        self.stack.addWidget(self.denuncias_page)
        self.busqueda_guias_page = BusquedaGuiasPage(); self.busqueda_guias_page.back_requested.connect(lambda: self.stack.setCurrentWidget(self.home_page))
        self.stack.addWidget(self.busqueda_guias_page)
        self.visitas_fotos_page = VisitasFotosPage()
        self.visitas_fotos_page.back_requested.connect(lambda: self.stack.setCurrentWidget(self.home_page))
        self.stack.addWidget(self.visitas_fotos_page)
        self.stack.currentChanged.connect(self._sync_navigation)
        self._sync_navigation()
        self.statusBar().showMessage("Listo")
        self._load_sellers_table()

    def _navigate(self, name):
        self.stack.setCurrentWidget(getattr(self, name))
        self._sync_navigation()

    def _sync_navigation(self, *_):
        for name, button in self.nav_buttons.items():
            button.setChecked(self.stack.currentWidget() is getattr(self, name, None))

    def _build_home_page(self):
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        page = QWidget(); scroll.setWidget(page)
        layout = QVBoxLayout(page); layout.setContentsMargins(0, 8, 0, 8); layout.setSpacing(22)
        label = QLabel("PANEL GENERAL"); label.setObjectName("eyebrow"); layout.addWidget(label)
        title = QLabel("Tu operación, más simple."); title.setStyleSheet("font-size:28px;font-weight:800;")
        title.setWordWrap(True); layout.addWidget(title)
        sub = QLabel("Consultá envíos, prepará reportes y gestioná tus chats desde un mismo espacio.")
        sub.setStyleSheet("color:#a5a7ba;font-size:14px;"); sub.setWordWrap(True); layout.addWidget(sub)
        tools = QHBoxLayout()
        self.archive_toggle_btn = QPushButton("Archivar / desarchivar")
        self.archive_toggle_btn.setProperty("primary", True)
        self.archive_toggle_btn.setToolTip("Si hay chats en Archivados, desarchiva todos. Si está vacío, archiva la lista Smart Post.")
        self.archive_toggle_btn.clicked.connect(lambda: self._toggle_whatsapp_archive("auto"))
        tools.addWidget(self.archive_toggle_btn); tools.addStretch(); layout.addLayout(tools)
        cards = QGridLayout(); cards.setHorizontalSpacing(16); cards.setVerticalSpacing(16)
        modules = (
            ("01", "Cambio de estado v2", "Actualizá pedidos por Rendición de Chofer con la fecha y el estado elegidos.", "cambio_estado_v2_page"),
            ("02", "Reportes y Visitas", "Descargá los Excel de Epresis y enviá los reportes a tus grupos.", "reports_page"),
            ("03", "Denuncias", "Prepará denuncias, abrí la carpeta de PDF y copiá los mensajes de la última denuncia.", "denuncias_page"),
            ("04", "Búsqueda de guías", "Encontrá envíos por guía, remito o guía agente y consultá sus datos.", "busqueda_guias_page"),
            ("05", "Visitas sin foto", "Detectá fotos pendientes según la cantidad de visitas de cada envío.", "visitas_fotos_page"),
        )
        for index, (number, title, body, target) in enumerate(modules):
            card = self._module_card(title, body, "Abrir módulo", number)
            card.findChild(QPushButton).clicked.connect(lambda checked=False, target=target: self.stack.setCurrentWidget(getattr(self, target)))
            cards.addWidget(card, index // 2, index % 2)
        cards.setColumnStretch(0, 1); cards.setColumnStretch(1, 1)
        layout.addLayout(cards); layout.addStretch(1)
        return scroll

    def _module_card(self, title_text, body_text, button_text, number=""):
        frame = QFrame(); frame.setObjectName("moduleCard")
        v = QVBoxLayout(frame); v.setContentsMargins(22, 20, 22, 20); v.setSpacing(12)
        tag = QLabel(number + "  /  MÓDULO"); tag.setObjectName("eyebrow"); v.addWidget(tag)
        title = QLabel(title_text); title.setWordWrap(True); title.setStyleSheet("font-size:20px;font-weight:700;")
        body = QLabel(body_text); body.setWordWrap(True); body.setStyleSheet("color:#a5a7ba;")
        btn = QPushButton(button_text); btn.setMinimumHeight(36); btn.setProperty("primary", True)
        v.addWidget(title); v.addWidget(body); v.addStretch(1); v.addWidget(btn)
        return frame

    def _build_reports_page(self):
        page = QWidget(); root = QVBoxLayout(page); root.setContentsMargins(8,8,8,8); root.setSpacing(12)
        nav = QHBoxLayout(); back = QPushButton("← Inicio"); back.clicked.connect(lambda: self.stack.setCurrentWidget(self.home_page))
        title = QLabel("Reportes y Visitas"); title.setStyleSheet("font-size:22px;font-weight:800;")
        nav.addWidget(back); nav.addWidget(title); nav.addStretch(1); root.addLayout(nav)

        controls = QHBoxLayout(); controls.addWidget(QLabel("Fecha del reporte:"))
        self.date = QDateEdit(QDate.currentDate()); self.date.setCalendarPopup(True); self.date.setDisplayFormat("dd-MM-yyyy"); self.date.setMinimumWidth(150)
        controls.addWidget(self.date)
        self.run_btn = QPushButton("Ejecutar"); self.dry_btn = QPushButton("Probar sin enviar"); self.open_reports_btn = QPushButton("Abrir reportes")
        self.run_btn.setProperty('primary', True)
        self.run_btn.clicked.connect(lambda: self._start_pipeline(False)); self.dry_btn.clicked.connect(lambda: self._start_pipeline(True)); self.open_reports_btn.clicked.connect(self._open_reports)
        for b in (self.run_btn,self.dry_btn,self.open_reports_btn): controls.addWidget(b)
        controls.addStretch(1); root.addLayout(controls)

        stages = QGroupBox("Progreso"); sg = QGridLayout(stages); self.stage_labels = {}
        for i,(key,label) in enumerate((("epresis","Epresis"),("reportes","Reportes"),("visitas","Visitas"),("whatsapp","WhatsApp"))):
            name=QLabel(label); name.setStyleSheet("font-weight:700;")
            state=QLabel("Pendiente"); state.setAlignment(Qt.AlignCenter); state.setMinimumWidth(130); state.setStyleSheet("padding:6px;border-radius:6px;background:#303244;color:#a5a7ba;")
            self.stage_labels[key]=state; sg.addWidget(name,0,i); sg.addWidget(state,1,i)
        self.progress=QProgressBar(); self.progress.setRange(0,100); self.progress.setValue(0); sg.addWidget(self.progress,2,0,1,4); root.addWidget(stages)

        body=QHBoxLayout(); logs_box=QGroupBox("Actividad en tiempo real"); lv=QVBoxLayout(logs_box)
        self.logs=QTextEdit(); self.logs.setReadOnly(True); self.logs.setLineWrapMode(QTextEdit.NoWrap); self.logs.setStyleSheet("font-family:Consolas,monospace;font-size:11px;")
        lv.addWidget(self.logs); body.addWidget(logs_box,2)
        summary_box=QGroupBox("Resumen por seller"); sv=QVBoxLayout(summary_box)
        self.summary=QTableWidget(0,4); self.summary.setHorizontalHeaderLabels(["Seller","Epresis","Reporte","WhatsApp"])
        self.summary.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch)
        for c in (1,2,3): self.summary.horizontalHeader().setSectionResizeMode(c,QHeaderView.ResizeToContents)
        self.summary.verticalHeader().setVisible(False); sv.addWidget(self.summary); body.addWidget(summary_box,3); root.addLayout(body,1)
        return page

    def _toggle_whatsapp_archive(self, mode="auto"):
        if self.chat_thread is not None:
            return
        self.archive_toggle_btn.setEnabled(False)
        self.statusBar().showMessage("Abriendo WhatsApp para archivar/desarchivar chats…")
        self.chat_thread = QThread(self)
        self.chat_worker = WhatsAppArchiveToggleWorker(mode)
        self.chat_worker.log_line.connect(self.statusBar().showMessage)
        self.chat_worker.moveToThread(self.chat_thread)
        self.chat_thread.started.connect(self.chat_worker.run)
        self.chat_worker.finished.connect(self._toggle_whatsapp_archive_finished)
        self.chat_worker.finished.connect(self.chat_thread.quit)
        self.chat_thread.finished.connect(self.chat_worker.deleteLater)
        self.chat_thread.finished.connect(self.chat_thread.deleteLater)
        self.chat_thread.finished.connect(self._clear_chat_worker)
        self.chat_thread.start()

    def _clear_chat_worker(self):
        self.chat_thread = None
        self.chat_worker = None

    def _toggle_whatsapp_archive_finished(self, ok: bool, result, detail: str):
        self.archive_toggle_btn.setEnabled(True)
        if not ok:
            self.statusBar().showMessage("Error al archivar/desarchivar chats")
            ErrorDialog(detail, self).exec()
            return
        mode = str((result or {}).get("mode") or "")
        count = int((result or {}).get("count") or 0)
        if mode == "unarchive":
            action = "desarchivado" if count == 1 else "desarchivados"
            text = f"{count} chat(s) {action}."
        else:
            action = "archivado" if count == 1 else "archivados"
            text = f"{count} chat(s) {action} desde Smart Post."
        self.statusBar().showMessage(text)
        QMessageBox.information(self, "WhatsApp", text)

    def _first_run_if_needed(self):
        cfg = load_config()
        if not cfg.get("app", {}).get("first_run_complete", False):
            wiz = InitialSetupWizard(self)
            if wiz.exec():
                self._load_sellers_table()
                QMessageBox.information(self, "Configuración guardada", "Configuración inicial completa. Ahora vinculá WhatsApp si todavía no está conectado.")

    def _load_sellers_table(self):
        if not hasattr(self, "summary"): return
        cfg=load_config(); sellers=cfg.get("sellers",[]); self.summary.setRowCount(len(sellers)+1)
        for r,s in enumerate(sellers):
            self.summary.setItem(r,0,QTableWidgetItem(str(s["seller"])))
            for c in (1,2,3): self.summary.setItem(r,c,QTableWidgetItem("—"))
        vr=len(sellers); item=QTableWidgetItem("VISITAS"); item.setBackground(QBrush(QColor("#303244"))); self.summary.setItem(vr,0,item)
        for c in (1,2,3): self.summary.setItem(vr,c,QTableWidgetItem("—"))

    def _set_busy(self,busy:bool):
        for b in (self.run_btn,self.dry_btn,self.settings_btn,self.login_btn): b.setEnabled(not busy)
        self.date.setEnabled(not busy)

    def _reset_stages(self):
        for label in self.stage_labels.values():
            label.setText("Pendiente"); label.setStyleSheet("padding:6px;border-radius:6px;background:#303244;color:#a5a7ba;")
        self.progress.setValue(0); self._load_sellers_table()

    def _stage(self,stage,status,payload):
        if stage in self.stage_labels:
            label=self.stage_labels[stage]
            if status=="running": label.setText("En curso…"); label.setStyleSheet("padding:6px;border-radius:6px;background:#463c2b;color:#f5cf85;")
            elif status=="ok": label.setText("✓ Completado"); label.setStyleSheet("padding:6px;border-radius:6px;background:#25433d;color:#95ddbb;")
            elif status=="error": label.setText("✗ Error"); label.setStyleSheet("padding:6px;border-radius:6px;background:#4b303d;color:#ffb4c1;")
        values={"epresis":8 if status=="running" else 28,"reportes":36 if status=="running" else 58,"visitas":64 if status=="running" else 76,"whatsapp":82 if status=="running" else 95}
        if stage in values:self.progress.setValue(max(self.progress.value(),values[stage]))
        if stage=="pipeline" and status=="ok":self.progress.setValue(100)

    def _start_pipeline(self,dry_run:bool):
        if not has_excel():
            QMessageBox.warning(self,"Microsoft Excel requerido","No se detectó Microsoft Excel de escritorio. SmartPost necesita Excel instalado para generar los reportes con la plantilla oficial."); return
        cfg=load_config(); missing=[s["seller"] for s in cfg["sellers"] if s.get("enabled",True) and not str(s.get("whatsapp_group","")).strip()]
        if missing:
            QMessageBox.warning(self,"Faltan grupos","Completá en Configuración los grupos de WhatsApp de:\n\n"+"\n".join(missing)); return
        visits_cfg=cfg.get("visitas") or {}
        if visits_cfg.get("enabled",True) and not str(visits_cfg.get("whatsapp_group","")).strip():
            QMessageBox.warning(self,"Falta grupo de Visitas","Completá en Configuración el grupo de WhatsApp para VISITAS."); return
        qd=self.date.date(); selected=datetime(qd.year(),qd.month(),qd.day()); self._reset_stages(); self.logs.clear(); self._set_busy(True)
        self.statusBar().showMessage("Ejecutando prueba…" if dry_run else "Ejecutando…")
        self.thread=QThread(self); self.worker=PipelineWorker(selected,dry_run); self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run); self.worker.log_line.connect(self.logs.append); self.worker.stage.connect(self._stage); self.worker.finished.connect(self._pipeline_finished); self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater); self.thread.finished.connect(self.thread.deleteLater); self.thread.start()

    def _pipeline_finished(self,code,summary,detail):
        self._set_busy(False); self._fill_summary(summary)
        if code==0:
            self.progress.setValue(100)
            pending=summary.get("whatsapp_pending",[]) or []
            if pending:
                self.statusBar().showMessage(f"Proceso finalizado con {len(pending)} envío(s) pendiente(s)")
                names="\n".join(f"• {x.get('seller')}: {x.get('reason','Error de WhatsApp')}" for x in pending)
                QMessageBox.warning(self,"SmartPost - envíos pendientes",f"Los reportes se generaron correctamente.\n\nQuedaron {len(pending)} envío(s) de WhatsApp pendientes después de los reintentos:\n\n{names}\n\nLos que figuran como enviados NO se volverán a enviar automáticamente.")
            else:
                self.statusBar().showMessage("Proceso finalizado correctamente")
                mode="Prueba finalizada: los mensajes quedaron preparados pero no se enviaron." if summary.get("dry_run") else "Proceso finalizado: los reportes fueron enviados correctamente."
                QMessageBox.information(self,"SmartPost",mode)
        else:
            self.statusBar().showMessage("Proceso detenido por un error"); ErrorDialog(detail or str(summary.get("fatal_error","Error desconocido")),self).exec()

    def _fill_summary(self,summary):
        cfg=load_config(); row_by={self.summary.item(r,0).text():r for r in range(self.summary.rowCount())}; ep=summary.get("epresis",{}) or {}
        for s in ep.get("downloaded",[]):self._cell(row_by.get(s),1,"✓ Descargado","ok")
        for s in ep.get("no_data",[]):self._cell(row_by.get(s),1,"Sin guías","warn")
        for s in (ep.get("errors",{}) or {}):self._cell(row_by.get(s),1,"✗ Error","bad")
        proc=summary.get("processing",{}) or {}
        for s in (proc.get("reports",{}) or {}):self._cell(row_by.get(s),2,"✓ OK","ok")
        for b in proc.get("blocked",[]) or []:
            s=b.get("seller");
            if s in row_by:self._cell(row_by[s],2,"✗ Bloqueado","bad")
        for item in summary.get("whatsapp",[]) or []:
            s=item.get("seller");status=item.get("status","")
            if s not in row_by:continue
            if status in {"sent","already_sent"}:self._cell(row_by[s],3,"✓ Enviado","ok")
            elif status=="preview_only":self._cell(row_by[s],3,"✓ Preparado","ok")
            else:self._cell(row_by[s],3,"✗ Error","bad")
        visits=summary.get("visitas",{}) or {};vr=row_by.get("VISITAS");vstatus=visits.get("status") or visits.get("download_status")
        if vstatus=="generated":
            rows=visits.get("rows");self._cell(vr,1,f"✓ {rows} registros" if rows is not None else "✓ Descargado","ok");self._cell(vr,2,"✓ XLSX","ok")
        elif vstatus=="no_data":self._cell(vr,1,"Sin registros","warn");self._cell(vr,2,"—","warn");self._cell(vr,3,"No enviado","warn")
        elif vstatus=="disabled":self._cell(vr,1,"Deshabilitado","warn");self._cell(vr,2,"—","warn");self._cell(vr,3,"—","warn")
        elif vstatus=="error":self._cell(vr,1,"✗ Error","bad")

    def _cell(self,row,col,text,kind):
        if row is None:return
        item=QTableWidgetItem(text);item.setTextAlignment(Qt.AlignCenter);colors={"ok":QColor("#25433d"),"warn":QColor("#463c2b"),"bad":QColor("#4b303d")};item.setBackground(QBrush(colors[kind]));self.summary.setItem(row,col,item)

    def _settings(self):
        if SettingsDialog(self).exec():self._load_sellers_table()

    def _login_whatsapp(self):
        QMessageBox.information(self,"Vincular WhatsApp","Se abrirá una ventana de WhatsApp Web. Si aparece un QR, escanealo con el teléfono. SmartPost cerrará la ventana automáticamente cuando detecte que la sesión quedó vinculada.")
        self._set_busy(True);self.statusBar().showMessage("Esperando vinculación de WhatsApp…");self.thread=QThread(self);self.worker=WhatsAppLoginWorker();self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run);self.worker.finished.connect(self._login_finished);self.worker.finished.connect(self.thread.quit);self.thread.finished.connect(self.worker.deleteLater);self.thread.finished.connect(self.thread.deleteLater);self.thread.start()

    def _login_finished(self,ok,detail):
        self._set_busy(False);self.statusBar().showMessage("Listo")
        if ok:QMessageBox.information(self,"WhatsApp",detail)
        else:ErrorDialog(detail,self).exec()

    def _open_reports(self):
        cfg=load_config();folder=resolve_path(cfg,"reports");folder.mkdir(parents=True,exist_ok=True);QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def closeEvent(self, event):
        if any(thread.isRunning() for thread in self.findChildren(QThread)):
            QMessageBox.information(self, "Proceso en curso", "Esperá a que termine el proceso antes de cerrar SmartPost.")
            event.ignore()
            return
        super().closeEvent(event)
