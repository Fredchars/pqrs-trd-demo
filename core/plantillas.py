"""Plantillas con variables {{variable}} y generación de PDF (fpdf2)."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime

from fpdf import FPDF

VARIABLE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
VARIABLES_DISPONIBLES = ["radicado", "nombre", "fecha_radicacion", "fecha_vencimiento", "empresa", "abogado",
                         "cargo", "asunto", "tipo", "codigo", "nueva_fecha", "motivo", "texto", "enlace_consulta",
                         "entidad"]


def render(texto: str, variables: dict) -> str:
    """Reemplaza {{variable}}. Las variables desconocidas se dejan visibles para corregirlas."""
    def _r(m):
        k = m.group(1)
        if k not in variables:
            return m.group(0)
        v = variables[k]
        return "" if v is None else str(v)
    return VARIABLE.sub(_r, texto or "")


def variables_faltantes(texto: str) -> list[str]:
    return sorted(set(VARIABLE.findall(texto or "")))


def _latin1(s: str) -> str:
    reemplazos = {"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-", "…": "...", "•": "-", "\u00a0": " "}
    for a, b in reemplazos.items():
        s = s.replace(a, b)
    return s.encode("latin-1", "replace").decode("latin-1")


def codigo_verificacion(radicado: str, contenido: str, fecha: datetime) -> str:
    return hashlib.sha256(f"{radicado}|{fecha.isoformat()}|{contenido}".encode()).hexdigest()[:16].upper()


def _rgb(hexcolor: str) -> tuple[int, int, int]:
    h = (hexcolor or "#1F3A5F").lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def pdf_respuesta(*, empresa: dict, radicado: str, destinatario: str, asunto: str, contenido: str,
                  firmante: str, cargo: str, fecha: datetime, codigo_verif: str, enlace: str,
                  es_parcial: bool = False, titulo: str = "Respuesta a su solicitud") -> bytes:
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(True, margin=20)
    pdf.add_page()
    r, g, b = _rgb(empresa.get("color"))
    # Logo ficticio: recuadro con las iniciales de la empresa
    pdf.set_fill_color(r, g, b)
    pdf.rect(15, 12, 18, 18, style="F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_xy(15, 17)
    pdf.cell(18, 8, _latin1(empresa.get("codigo", "")[-2:]), align="C")
    pdf.set_text_color(r, g, b)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_xy(37, 13)
    pdf.cell(0, 7, _latin1(empresa.get("nombre", "")))
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(90, 90, 90)
    pdf.set_xy(37, 20)
    pdf.cell(0, 5, _latin1(f"NIT {empresa.get('nit', '')} · {empresa.get('buzon_correo', '')}"))
    pdf.set_xy(37, 25)
    pdf.set_text_color(170, 30, 30)
    pdf.cell(0, 5, _latin1("DOCUMENTO DE PRUEBA - DATOS FICTICIOS (PROTOTIPO BETA)"))
    pdf.set_text_color(20, 20, 20)
    pdf.set_y(38)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, _latin1(titulo + (" (RESPUESTA PARCIAL)" if es_parcial else "")), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _latin1(f"Radicado: {radicado}    Fecha: {fecha:%d/%m/%Y %H:%M}"), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, _latin1(f"Destinatario: {destinatario}"), new_x="LMARGIN", new_y="NEXT")
    pdf.multi_cell(0, 6, _latin1(f"Asunto: {asunto}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 6, _latin1(contenido), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, _latin1(firmante), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 5, _latin1(cargo), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, _latin1(empresa.get("nombre", "")), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_draw_color(r, g, b)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(70, 70, 70)
    pdf.multi_cell(0, 4.5, _latin1(
        f"Firma electrónica simple (beta). Código de verificación: {codigo_verif}. "
        f"Consulte la autenticidad y el estado de su caso en {enlace} con su número de radicado y código de consulta. "
        "La firma digital certificada se implementará en producción."), border="T", new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def pdf_texto(titulo: str, lineas: list[str]) -> bytes:
    """PDF simple (acuses impresos, trazabilidad R8)."""
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 13)
    pdf.multi_cell(0, 7, _latin1(titulo), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(170, 30, 30)
    pdf.cell(0, 5, _latin1("PROTOTIPO BETA - DATOS FICTICIOS"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(20, 20, 20)
    pdf.set_font("Helvetica", "", 9)
    for ln in lineas:
        pdf.multi_cell(0, 5, _latin1(ln), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
