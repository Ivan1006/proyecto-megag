"""Inserta runs de prueba en SQLite para validar la UI sin conexión a Gmail."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from . import db


def run() -> None:
    db.init_db()

    samples = [
        {
            "thread_id": "tg-001-cafe-chinchina",
            "last_message_id": "msg-001a",
            "subject": "Solicitud crédito agropecuario — Café variedad Castillo",
            "sender": "maria.gomez@cafedelaesperanza.co",
            "sender_name": "María Gómez Restrepo",
            "status": "generated",
            "fields": {
                "beneficiario_razon_social": "María Gómez Restrepo",
                "beneficiario_id_tipo": "C.C.",
                "beneficiario_id_numero": "43.185.672",
                "predio_nombre_direccion": "La Esperanza — Vereda El Vergel",
                "monto_total_activos": 180000000,
                "actividad_economica_codigo": "0127",
                "fag_cobertura_pct": 80,
            },
            "completitud_req": 1.0,
            "completitud_opt": 0.75,
            "aprobado": 1,
            "messages": [
                ("msg-001a", "María Gómez Restrepo", "maria.gomez@cafedelaesperanza.co",
                 "Solicitud crédito agropecuario — Café",
                 "Buenos días, adjunto los documentos para mi solicitud de crédito agropecuario. "
                 "Quiero renovar 5 has de café variedad Castillo en la finca La Esperanza, Chinchiná.",
                 ["RUT.pdf", "balance.xlsx", "carta_insumos.pdf"]),
                ("msg-001b", "María Gómez Restrepo", "maria.gomez@cafedelaesperanza.co",
                 "Re: Solicitud crédito agropecuario — Café",
                 "Ojo, la cédula correcta es 43.185.672 (en el RUT está como 43185672). "
                 "Adjunto también la última declaración de renta.",
                 ["renta_2025.pdf"]),
            ],
            "gaps": [],
            "minutes_ago": 90,
        },
        {
            "thread_id": "tg-002-aguacate-quindio",
            "last_message_id": "msg-002a",
            "subject": "Crédito siembra aguacate Hass",
            "sender": "jp.cardenas@agroquindio.com",
            "sender_name": "Juan Pablo Cárdenas",
            "status": "incomplete",
            "fields": {
                "beneficiario_razon_social": "Juan Pablo Cárdenas",
                "beneficiario_id_tipo": "C.C.",
                "predio_nombre_direccion": "Lote 4 — Vereda La Cumbre",
            },
            "completitud_req": 0.55,
            "completitud_opt": 0.20,
            "aprobado": 0,
            "messages": [
                ("msg-002a", "Juan Pablo Cárdenas", "jp.cardenas@agroquindio.com",
                 "Crédito siembra aguacate Hass",
                 "Cordial saludo, requiero crédito para sembrar 3 hectáreas de aguacate Hass.",
                 ["proyecto.docx"]),
            ],
            "gaps": [
                {"field_id": "beneficiario_id_numero", "tipo": "faltante",
                 "descripcion": "No se encontró número de identificación",
                 "sugerencia": "Solicitar copia del RUT"},
                {"field_id": "predio_extension_has", "tipo": "faltante",
                 "descripcion": "Falta extensión del predio en hectáreas",
                 "sugerencia": "Pedir certificado de tradición"},
                {"field_id": "monto_total_activos", "tipo": "faltante",
                 "descripcion": "Falta balance financiero",
                 "sugerencia": "Adjuntar estados financieros del último periodo"},
            ],
            "minutes_ago": 240,
        },
        {
            "thread_id": "tg-003-ganaderia-cesar",
            "last_message_id": "msg-003c",
            "subject": "Solicitud sostenimiento ganadería doble propósito",
            "sender": "finca.elparaiso@gmail.com",
            "sender_name": "Hacienda El Paraíso",
            "status": "failed",
            "fields": {},
            "completitud_req": 0.0,
            "completitud_opt": 0.0,
            "aprobado": 0,
            "error": "Parseo del PDF falló: archivo corrupto o protegido con contraseña.",
            "messages": [
                ("msg-003a", "Hacienda El Paraíso", "finca.elparaiso@gmail.com",
                 "Solicitud sostenimiento ganadería",
                 "Adjunto solicitud para sostenimiento de hato ganadero (250 cabezas).",
                 ["solicitud.pdf"]),
                ("msg-003b", "Hacienda El Paraíso", "finca.elparaiso@gmail.com",
                 "Re: Solicitud sostenimiento ganadería",
                 "Reenvío el PDF, parece que no abrió bien.",
                 ["solicitud_v2.pdf"]),
                ("msg-003c", "Hacienda El Paraíso", "finca.elparaiso@gmail.com",
                 "Re: Solicitud sostenimiento ganadería",
                 "Probaron abrirlo? Sigue dando error?", []),
            ],
            "gaps": [],
            "minutes_ago": 1440,
        },
        {
            "thread_id": "tg-004-arroz-tolima",
            "last_message_id": "msg-004a",
            "subject": "Crédito producción arroz secano",
            "sender": "asociacion@arroceros-tolima.org",
            "sender_name": "Asociación Arroceros Tolima",
            "status": "extracted",
            "fields": {"beneficiario_razon_social": "Asociación Arroceros Tolima"},
            "completitud_req": 0.30,
            "completitud_opt": 0.10,
            "aprobado": 0,
            "messages": [
                ("msg-004a", "Asociación Arroceros Tolima", "asociacion@arroceros-tolima.org",
                 "Crédito producción arroz secano",
                 "Buen día, solicitamos crédito para 50 hectáreas de arroz secano en El Espinal.",
                 ["camara_comercio.pdf", "rut.pdf"]),
            ],
            "gaps": [],
            "minutes_ago": 30,
        },
        {
            "thread_id": "tg-005-pina-santander",
            "last_message_id": "msg-005a",
            "subject": "Solicitud renovación cultivo piña MD2",
            "sender": "carlos.pineda@fincalospinos.co",
            "sender_name": "Carlos Pineda",
            "status": "generated",
            "fields": {
                "beneficiario_razon_social": "Carlos Eduardo Pineda Ortega",
                "beneficiario_id_tipo": "C.C.",
                "beneficiario_id_numero": "91.234.567",
                "monto_total_activos": 95000000,
            },
            "completitud_req": 1.0,
            "completitud_opt": 0.90,
            "aprobado": 1,
            "messages": [
                ("msg-005a", "Carlos Pineda", "carlos.pineda@fincalospinos.co",
                 "Renovación cultivo piña MD2",
                 "Adjunto documentación completa para crédito de renovación de 8 has de piña MD2.",
                 ["rut.pdf", "balance.xlsx", "camara_comercio.pdf", "carta_insumos.pdf"]),
            ],
            "gaps": [],
            "minutes_ago": 10,
        },
    ]

    now = datetime.now(timezone.utc)
    for s in samples:
        started = now - timedelta(minutes=s["minutes_ago"])
        run_id = db.create_run(
            thread_id=s["thread_id"],
            last_message_id=s["last_message_id"],
            subject=s["subject"],
            sender=s["sender"],
            sender_name=s["sender_name"],
            received_at=started,
        )
        duration_ms = random.randint(8000, 45000)
        finished = started + timedelta(milliseconds=duration_ms)
        db.update_run(
            run_id,
            status=s["status"],
            started_at=started.isoformat(),
            finished_at=finished.isoformat() if s["status"] != "pending" else None,
            duration_ms=duration_ms,
            fields_json=s["fields"],
            completitud_req=s["completitud_req"],
            completitud_opt=s["completitud_opt"],
            aprobado=s["aprobado"],
            error=s.get("error"),
            excel_path=f"./data/output/{s['thread_id']}/solicitud_credito.xlsx"
            if s["status"] == "generated"
            else None,
            pdf_path=f"./data/output/{s['thread_id']}/solicitud_credito.pdf"
            if s["status"] == "generated"
            else None,
        )
        msgs = []
        base = started - timedelta(minutes=60)
        for i, (mid, name, email, subject, body, atts) in enumerate(s["messages"]):
            msgs.append({
                "message_id": mid,
                "sender": email,
                "sender_name": name,
                "subject": subject,
                "received_at": (base + timedelta(minutes=i * 20)).isoformat(),
                "body_preview": body,
                "attachments": atts,
            })
        db.save_messages(run_id, msgs)
        db.save_gaps(run_id, s.get("gaps", []))


if __name__ == "__main__":
    run()
    print("Seed listo.")
