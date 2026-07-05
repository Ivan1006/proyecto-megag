"""Investigación web de la razón social del beneficiario.

Apoya al `code_resolver` cuando el correo es pobre y no describe bien la
actividad económica del cliente: busca la razón social en la web (Tavily),
resume a qué se dedica la empresa y detecta discrepancias con lo que dice el
correo.

**Regla de oro**: el correo SIEMPRE manda. La web solo (a) aporta contexto al
resolver y (b) genera un flag de discrepancia para el dashboard; nunca
sobrescribe lo que dice el correo.
"""
