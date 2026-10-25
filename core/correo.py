"""Correo: IMAP/SMTP real (Gmail beta con contraseña de aplicación) o buzón SIMULADO en la base de datos.

Sin MAIL_USER / MAIL_APP_PASSWORD todo correo de salida queda en la tabla `correos`
(visible en la página «Buzón simulado») y se pueden simular correos entrantes de ciudadanos.
"""
from __future__ import annotations

import email
import imaplib
import smtplib
import ssl
from email import policy
from email.message import EmailMessage
from email.utils import formatdate, getaddresses, make_msgid, parseaddr

from core import config
from core.reloj import ahora

AVISO_SIMULADO = ("CORREO SIMULADO: no se envió ningún correo real. Los mensajes quedan en la página «Buzón simulado». "
                  "Para envío real configure MAIL_USER y MAIL_APP_PASSWORD (y opcionalmente MAIL_SMTP_HOST, MAIL_SMTP_PORT, "
                  "MAIL_IMAP_HOST, MAIL_FROM) en los secretos.")


def modo() -> str:
    return "real" if config.correo_real_activo() else "simulado"


def remitente() -> str:
    return config.correo_servidor()["remitente"] or "pqrs-beta@pqrs.example.com"


def construir(de: str, para: str, asunto: str, cuerpo: str, adjuntos=None, en_respuesta_a: str | None = None) -> EmailMessage:
    m = EmailMessage()
    m["From"] = de
    m["To"] = para
    m["Subject"] = asunto
    m["Date"] = formatdate(localtime=True)
    m["Message-ID"] = make_msgid(domain="pqrs.example.com")
    if en_respuesta_a:
        m["In-Reply-To"] = en_respuesta_a
    m.set_content(cuerpo)
    for nombre, datos, mime in adjuntos or []:
        mt, _, st = (mime or "application/octet-stream").partition("/")
        m.add_attachment(datos, maintype=mt, subtype=st or "octet-stream", filename=nombre)
    return m


def enviar(repo, para: str, asunto: str, cuerpo: str, adjuntos=None, solicitud_id: int | None = None) -> dict:
    """Envía (o simula) un correo y lo registra en la tabla `correos`. Nunca lanza: devuelve el estado."""
    msg = construir(remitente(), para, asunto, cuerpo, adjuntos)
    estado, error = "enviado", None
    if modo() == "real":
        try:
            srv = config.correo_servidor()
            ctx = ssl.create_default_context()
            if srv["smtp_starttls"]:
                s = smtplib.SMTP(srv["smtp_host"], srv["smtp_port"], timeout=30)
                s.starttls(context=ctx)
            else:
                s = smtplib.SMTP_SSL(srv["smtp_host"], srv["smtp_port"], context=ctx, timeout=30)
            with s:
                s.login(config.obtener("MAIL_USER"), config.obtener("MAIL_APP_PASSWORD"))
                s.send_message(msg)
        except Exception as e:  # rebote / error de envío
            estado, error = "error", f"{type(e).__name__}: {e}"[:300]
    else:
        estado = "simulado"
    cid = repo.insertar("correos", {
        "direccion": "salida", "modo": modo(), "message_id": msg["Message-ID"], "de": msg["From"], "para": para,
        "asunto": asunto, "cuerpo": cuerpo, "eml": msg.as_string(), "solicitud_id": solicitud_id,
        "estado": estado, "error": error, "fecha": ahora()})
    return {"id": cid, "estado": estado, "error": error, "message_id": msg["Message-ID"]}


def simular_entrante(repo, de: str, para: str, asunto: str, cuerpo: str, adjuntos=None) -> int:
    """Deja un correo de ciudadano en el buzón simulado; la tarea `leer_correo` lo procesará."""
    msg = construir(de, para, asunto, cuerpo, adjuntos)
    return repo.insertar("correos", {
        "direccion": "entrada", "modo": "simulado", "message_id": msg["Message-ID"], "de": de, "para": para,
        "asunto": asunto, "cuerpo": cuerpo, "eml": msg.as_string(), "estado": "pendiente", "fecha": ahora()})


def leer_nuevos(repo, limite: int = 50) -> list[tuple[int | None, bytes]]:
    """Devuelve [(id_correo_simulado | None, eml_bytes)] de los correos no procesados."""
    salida: list[tuple[int | None, bytes]] = []
    if modo() == "real":
        try:
            srv = config.correo_servidor()
            im = imaplib.IMAP4_SSL(srv["imap_host"], srv["imap_port"])
            im.login(config.obtener("MAIL_USER"), config.obtener("MAIL_APP_PASSWORD"))
            im.select("INBOX")
            _, datos = im.search(None, "UNSEEN")
            for num in (datos[0].split() or [])[:limite]:
                _, partes = im.fetch(num, "(RFC822)")
                salida.append((None, partes[0][1]))
            im.logout()
        except Exception as e:
            repo.insertar("eventos", {"origen": "sistema", "accion": "error_imap", "detalle": {"error": str(e)[:300]},
                                      "fecha": ahora()})
    filas = repo.q("select id, eml from correos where direccion = 'entrada' and estado = 'pendiente' order by id limit ?",
                   [limite])
    salida.extend((f["id"], (f["eml"] or "").encode("utf-8")) for f in filas)
    return salida


def parsear(eml: bytes) -> dict:
    msg = email.message_from_bytes(eml, policy=policy.default)
    cuerpo = msg.get_body(preferencelist=("plain", "html"))
    texto = cuerpo.get_content() if cuerpo else ""
    adjuntos = []
    for parte in msg.iter_attachments():
        nombre = parte.get_filename() or "adjunto"
        adjuntos.append((nombre, parte.get_payload(decode=True) or b"", parte.get_content_type()))
    nombre, direccion = parseaddr(msg.get("From", ""))
    return {
        "message_id": (msg.get("Message-ID") or "").strip() or make_msgid(),
        "de": direccion.lower(), "nombre": nombre or direccion.split("@")[0],
        "para": [a.lower() for _, a in getaddresses((msg.get_all("To") or []) + (msg.get_all("Cc") or [])) if a],
        "asunto": str(msg.get("Subject", "")).strip(), "cuerpo": texto.strip(), "adjuntos": adjuntos,
    }
