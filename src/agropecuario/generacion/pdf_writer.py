"""Conversión Excel → PDF usando LibreOffice headless.

Es la forma más fiable de preservar el layout exacto del formulario oficial
sin reimplementar plantillas HTML/CSS.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..logging_conf import get_logger

logger = get_logger(__name__)

SOFFICE_BIN = "soffice"  # también acepta "libreoffice"


def render_pdf(excel_path: Path, output_path: Path, timeout: int = 120) -> Path:
    """Genera el PDF a partir del Excel ya rellenado.

    `output_path` es el archivo .pdf de destino. LibreOffice escribe el PDF
    en el `--outdir` con el mismo basename del Excel; lo movemos al destino final.
    """
    if shutil.which(SOFFICE_BIN) is None and shutil.which("libreoffice") is None:
        raise RuntimeError(
            "LibreOffice no está instalado. Instala con `sudo apt install libreoffice-calc`."
        )
    binary = SOFFICE_BIN if shutil.which(SOFFICE_BIN) else "libreoffice"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        binary,
        "--headless",
        "--convert-to", "pdf",
        "--outdir", str(output_path.parent),
        str(excel_path),
    ]
    logger.info("pdf.converting", cmd=" ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        logger.error("pdf.convert_failed", stderr=result.stderr)
        raise RuntimeError(f"LibreOffice falló: {result.stderr}")

    generated = output_path.parent / (excel_path.stem + ".pdf")
    if generated != output_path:
        generated.replace(output_path)

    logger.info("pdf.rendered", path=str(output_path))
    return output_path
