from app.delivery.chat_archive import _flexible_text_pattern


def test_company_list_name_accepts_counter_and_spacing():
    p = _flexible_text_pattern("Smart Post")
    assert p.fullmatch("Smart Post")
    assert p.fullmatch("Smart Post 14")
    assert p.fullmatch("SmartPost 14")
    assert p.fullmatch(" smart   post 28 ")
    assert not p.fullmatch("Smart Poster")
