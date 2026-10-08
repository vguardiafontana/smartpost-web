from app.cambio_estado.service import extract_identifiers
from app.delivery.chat_archive import _ARCHIVE_RE, _UNARCHIVE_RE, _ARCHIVED_RE


def test_direct_change_input_still_dedupes_exact_identifiers():
    assert extract_identifiers('6190808 6190808 48081585158') == ['6190808', '48081585158']


def test_whatsapp_archive_labels_support_spanish_and_english():
    assert _ARCHIVED_RE.match('Archivados')
    assert _ARCHIVED_RE.match('Archived')
    assert _ARCHIVE_RE.match('Archivar chat')
    assert _ARCHIVE_RE.match('Archive chat')
    assert _UNARCHIVE_RE.match('Desarchivar chat')
    assert _UNARCHIVE_RE.match('Unarchive chat')
