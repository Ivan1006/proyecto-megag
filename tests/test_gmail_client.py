"""Tests de autenticación del GmailClient.

Reproduce el bug: un token cacheado con refresh token caducado (típico del modo
Testing de Google, que invalida el refresh token a los 7 días) hacía que
`authenticate()` reventara con `RefreshError` en vez de caer al login interactivo.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from google.auth.exceptions import RefreshError

from agropecuario.ingesta import gmail_client as gc


def _dead_creds() -> MagicMock:
    """Credenciales expiradas cuyo refresh falla (refresh token muerto)."""
    creds = MagicMock()
    creds.valid = False
    creds.expired = True
    creds.refresh_token = "rt-caducado"
    creds.refresh.side_effect = RefreshError("invalid_grant: Bad Request")
    return creds


@pytest.fixture
def token_file(tmp_path):
    p = tmp_path / "token.json"
    p.write_text("{}")  # solo debe existir; el parseo está mockeado
    return p


def test_refresh_caducado_cae_a_interactivo(monkeypatch, token_file):
    """Si el refresh token está muerto, debe lanzar el flujo OAuth interactivo."""
    monkeypatch.setattr(
        gc.Credentials, "from_authorized_user_file",
        lambda *a, **k: _dead_creds(),
    )

    fresh = MagicMock()
    fresh.valid = True
    fresh.to_json.return_value = '{"token": "nuevo"}'
    flow = MagicMock()
    flow.run_local_server.return_value = fresh
    monkeypatch.setattr(
        gc.InstalledAppFlow, "from_client_secrets_file",
        lambda *a, **k: flow,
    )
    monkeypatch.setattr(gc, "build", lambda *a, **k: MagicMock())

    client = gc.GmailClient()
    client.settings.google_token_path = token_file

    # No debe propagar RefreshError.
    client.authenticate(interactive=True)

    # Cayó al login interactivo y reescribió el token con las credenciales nuevas.
    flow.run_local_server.assert_called_once()
    assert token_file.read_text() == '{"token": "nuevo"}'


def test_refresh_caducado_no_interactivo_lanza_runtimeerror(monkeypatch, token_file):
    """En modo no-interactivo, un refresh muerto da RuntimeError, no RefreshError."""
    monkeypatch.setattr(
        gc.Credentials, "from_authorized_user_file",
        lambda *a, **k: _dead_creds(),
    )
    monkeypatch.setattr(gc, "build", lambda *a, **k: MagicMock())

    client = gc.GmailClient()
    client.settings.google_token_path = token_file

    with pytest.raises(RuntimeError):
        client.authenticate(interactive=False)
