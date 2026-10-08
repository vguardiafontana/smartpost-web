from types import SimpleNamespace

from app.descarga import credentials


def test_get_credentials_prefers_cloud_env(monkeypatch):
    monkeypatch.setenv(credentials.ENV_USER, "cloud-user")
    monkeypatch.setenv(credentials.ENV_PASSWORD, "cloud-pass")
    fake = SimpleNamespace(get_password=lambda *args: (_ for _ in ()).throw(AssertionError("no keyring")))
    monkeypatch.setattr(credentials, "keyring", fake)

    assert credentials.get_credentials() == ("cloud-user", "cloud-pass")


def test_get_credentials_keeps_desktop_keyring_fallback(monkeypatch):
    monkeypatch.delenv(credentials.ENV_USER, raising=False)
    monkeypatch.delenv(credentials.ENV_PASSWORD, raising=False)

    values = {"username": "desktop-user", "password": "desktop-pass"}
    fake = SimpleNamespace(get_password=lambda _service, key: values[key])
    monkeypatch.setattr(credentials, "keyring", fake)

    assert credentials.get_credentials() == ("desktop-user", "desktop-pass")


def test_partial_cloud_env_does_not_override_desktop_credentials(monkeypatch):
    monkeypatch.setenv(credentials.ENV_USER, "cloud-user")
    monkeypatch.delenv(credentials.ENV_PASSWORD, raising=False)

    values = {"username": "desktop-user", "password": "desktop-pass"}
    fake = SimpleNamespace(get_password=lambda _service, key: values[key])
    monkeypatch.setattr(credentials, "keyring", fake)

    assert credentials.get_credentials() == ("desktop-user", "desktop-pass")
