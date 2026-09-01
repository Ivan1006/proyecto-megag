"""El grafo LangGraph se construye y ya no tiene paso de subida remota.

Google Drive se descartó (2026-08-29): los entregables se quedan en disco y la
entrega definitiva —correo o una ruta de NAS— está sin definir. El grafo no
estaba cubierto por ningún test, así que se fija aquí lo mínimo: que compile y
que nada dependa de un cliente de Drive.

El `runner` es el camino que corre de verdad hoy; este grafo es el que usa
`agropecuario run`.
"""

from __future__ import annotations

import pytest

from agropecuario.agents.generacion import make_generacion_node
from agropecuario.models import GeneratedOutputs


def test_el_grafo_compila():
    """`build_graph()` ya no recibe `enable_drive` ni construye DriveClient."""
    from agropecuario.orchestrator import build_graph

    app = build_graph()
    assert app is not None


def test_el_nodo_de_generacion_no_pide_cliente_de_drive():
    node = make_generacion_node()  # antes exigía (o aceptaba) un DriveClient
    assert callable(node)


def test_los_entregables_no_tienen_urls_remotas():
    """Regresión: `GeneratedOutputs` solo describe rutas locales."""
    campos = set(GeneratedOutputs.model_fields)
    assert campos == {"pdf_path", "excel_path", "generated_at"}


def test_no_queda_modulo_de_drive():
    with pytest.raises(ModuleNotFoundError):
        import agropecuario.storage.drive_client  # noqa: F401
