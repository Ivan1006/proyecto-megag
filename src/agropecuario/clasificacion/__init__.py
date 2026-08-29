"""Reglas de negocio Finagro sobre el beneficiario del crédito.

A diferencia de `catalogo/` (que resuelve el destino del crédito contra el Anexo)
aquí viven las clasificaciones que el Manual de Servicios define sobre la persona
o empresa que pide el crédito.
"""

from .tamano_productor import (
    Clasificacion,
    TamanoProductor,
    clasificar,
    load_config,
)

__all__ = ["Clasificacion", "TamanoProductor", "clasificar", "load_config"]
