"""Carga de documentos: validación, huella SHA-256, nombre normalizado y extracción de texto."""
from __future__ import annotations

import email
import hashlib
import io
import re
import unicodedata
from datetime import datetime
from email import policy

CATEGORIAS = {
    "entrada": "01_entrada",
    "trabajo": "02_trabajo",
    "respuesta": "03_respuesta",
    "soporte": "04_soportes",
}
NOMBRES_CATEGORIA = {
    "entrada": "Entrada (solicitud y adjuntos del ciudadano)",
    "trabajo": "Trabajo (borradores, notas, soportes internos)",
    "respuesta": "Respuesta (PDF enviado y constancias)",
    "soporte": "Soportes (información aportada, traslados, prórrogas)",
}
EXTENSIONES = {"pdf", "docx", "xlsx", "jpg", "jpeg", "png", "eml", "txt"}
INMUTABLES = {"entrada", "respuesta"}


class ErrorDocumento(ValueError):
    pass


def sha256(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def extension(nombre: str) -> str:
    return nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""


def validar(nombre: str, tamano: int, total_previo: int = 0, max_mb: float = 10, max_total_mb: float = 25,
            permitidas: set[str] | None = None) -> None:
    """Lanza ErrorDocumento con un mensaje que dice qué pasó y qué hacer."""
    ext = extension(nombre)
    perm = permitidas or EXTENSIONES
    if ext not in perm:
        raise ErrorDocumento(
            f"El archivo «{nombre}» no es de un tipo permitido. Envíelo como PDF, DOCX, XLSX, JPG, PNG o EML.")
    if tamano > max_mb * 1024 * 1024:
        raise ErrorDocumento(f"El archivo «{nombre}» supera {max_mb:g} MB. Comprímalo o divídalo.")
    if total_previo + tamano > max_total_mb * 1024 * 1024:
        raise ErrorDocumento(
            f"Los archivos de esta solicitud superan {max_total_mb:g} MB en total. Envíe solo los más importantes "
            "o divídalos en varios envíos.")


def slug(nombre: str) -> str:
    base = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-")
    return base[:80] or "archivo"


def nombre_normalizado(radicado: str, categoria: str, fecha: datetime, version: int, original: str) -> str:
    """{RADICADO}_{categoria}_{AAAAMMDD-HHMM}_{v#}_{nombre-original}"""
    return f"{radicado}_{categoria}_{fecha:%Y%m%d-%H%M}_v{version}_{slug(original)}"


def ruta(empresa: str, anio: int, tipo: str, radicado: str, categoria: str, nombre: str) -> str:
    return f"{empresa}/{anio}/{tipo}/{radicado}/{CATEGORIAS[categoria]}/{nombre}"


def extraer_texto(nombre: str, datos: bytes) -> tuple[str | None, str]:
    """Devuelve (texto, estado). estado: 'ok', 'pendiente_ocr' (escaneado sin texto) o 'no_aplica'."""
    ext = extension(nombre)
    try:
        if ext == "pdf":
            from pypdf import PdfReader
            r = PdfReader(io.BytesIO(datos))
            texto = "\n".join((p.extract_text() or "") for p in r.pages).strip()
            return (texto, "ok") if texto else (None, "pendiente_ocr")
        if ext == "docx":
            import docx
            d = docx.Document(io.BytesIO(datos))
            partes = [p.text for p in d.paragraphs]
            for t in d.tables:
                for fila in t.rows:
                    partes.extend(c.text for c in fila.cells)
            texto = "\n".join(x for x in partes if x).strip()
            return (texto, "ok") if texto else (None, "no_aplica")
        if ext == "eml":
            msg = email.message_from_bytes(datos, policy=policy.default)
            cuerpo = msg.get_body(preferencelist=("plain", "html"))
            texto = f"{msg.get('subject', '')}\n{cuerpo.get_content() if cuerpo else ''}".strip()
            return texto, "ok"
        if ext == "txt":
            return datos.decode("utf-8", "replace"), "ok"
        if ext in ("jpg", "jpeg", "png"):
            return None, "pendiente_ocr"
    except Exception:
        return None, "error_extraccion"
    return None, "no_aplica"
