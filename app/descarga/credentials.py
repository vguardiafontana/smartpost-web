from __future__ import annotations

import os

try:
    import keyring  # type: ignore
except Exception:  # pragma: no cover - only relevant on minimal/cloud installs
    keyring = None

SERVICE = "SmartPost-Epresis"
ENV_USER = "SMARTPOST_EPRESIS_USER"
ENV_PASSWORD = "SMARTPOST_EPRESIS_PASSWORD"


def get_credentials() -> tuple[str | None, str | None]:
    """Obtiene credenciales de Epresis de forma portable.

    En servidor/cloud se inyectan como secretos de entorno. En Windows, si esas
    variables no existen, se conserva el keyring actual sin cambiar el flujo.
    """
    env_user = (os.environ.get(ENV_USER) or "").strip()
    env_password = os.environ.get(ENV_PASSWORD) or ""
    if env_user and env_password:
        return env_user, env_password

    if keyring is None:
        return None, None
    try:
        user = keyring.get_password(SERVICE, "username")
        password = keyring.get_password(SERVICE, "password")
    except Exception:
        return None, None
    return user, password


def save_credentials(user: str, password: str) -> None:
    user = (user or "").strip()
    if not user:
        raise ValueError("El usuario de Epresis no puede estar vacío.")
    if not password:
        raise ValueError("La contraseña de Epresis no puede estar vacía.")
    if keyring is None:
        raise RuntimeError("El keyring del sistema no está disponible en este entorno.")
    keyring.set_password(SERVICE, "username", user)
    keyring.set_password(SERVICE, "password", password)
