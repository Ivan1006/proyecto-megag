from pathlib import Path

from agropecuario.generacion.template_engine import load_template

TEMPLATE = Path(__file__).parent.parent / "config" / "template.yaml"


def test_template_loads():
    t = load_template(TEMPLATE)
    assert t.version >= 1
    assert any(s.id == "datos_generales" for s in t.secciones)
    assert any(s.generado_por_llm for s in t.secciones)
    assert any(c.id == "monto_por_hectarea" for c in t.calculados)
