from pathlib import Path

import yaml


def test_desktop_pushes_publish_only_after_installer_validation():
    workflow = yaml.load(Path('.github/workflows/build-installer.yml').read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
    assert workflow['on']['push']['branches'] == ['main']
    assert 'app/**' in workflow['on']['push']['paths']
    assert '!app/web/**' in workflow['on']['push']['paths']
    assert workflow['permissions']['contents'] == 'read'
    release = workflow['jobs']['release']
    assert release['needs'] == 'build'
    assert release['permissions']['contents'] == 'write'
    steps = workflow['jobs']['build']['steps']
    installer_test = next(i for i, step in enumerate(steps) if step.get('name') == 'Test a clean installation')
    upload = next(i for i, step in enumerate(steps) if 'upload-artifact' in step.get('uses', ''))
    assert installer_test < upload
    assert '--self-test' in steps[installer_test]['run']
    publish = release['steps'][-1]['run']
    assert publish.index('gh release upload') < publish.index('gh release edit')
    assert '--draft' in publish


def test_self_test_branches_before_loading_user_config():
    import ast
    tree = ast.parse(Path('desktop.py').read_text(encoding='utf-8'))
    assert not any(isinstance(node, ast.ImportFrom) and node.module == 'app.core.config' for node in tree.body)
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
    assert isinstance(main.body[0], ast.If)
    assert '--self-test' in ast.unparse(main.body[0])


def test_all_gui_modules_load_with_the_desktop_updates(tmp_path):
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication
    from app.denuncias.history import save_history
    from app.gui.denuncias_history_dialog import DenunciasHistoryDialog
    from app.gui.cambio_estado_v2_page import CambioEstadoV2Page
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/arial.ttf')
    app.setFont(QFont('Arial', 10))
    pdf = tmp_path / 'DENUNCIA.pdf'; pdf.write_bytes(b'%PDF-test')
    save_history(pdf, [{'seller': 'SELLER', 'remito': '00123'}], {})
    dialog = DenunciasHistoryDialog(tmp_path)
    assert dialog.sellers.currentText() == 'SELLER'
    dialog.copy_btn.click()
    assert '00123' in app.clipboard().text()
    page = CambioEstadoV2Page()
    assert page.date_edit.calendarPopup()
    dialog.close(); page.close()
