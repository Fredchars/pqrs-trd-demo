"""Formulario de radicación (público y de ventanilla)."""
from __future__ import annotations

import streamlit as st

import ui
from core import consultas as C
from core import plantillas
from core import servicios as S
from core.reloj import fmt_fecha, fmt_fechahora


def acuse_pdf(res: dict) -> bytes:
    s = res["solicitud"]
    return plantillas.pdf_texto(f"Acuse de recibo · {s['empresa_nombre']}", [
        f"Radicado: {s['radicado']}", f"Código de consulta: {res['codigo']}",
        f"Recibida: {fmt_fechahora(s['fecha_recepcion'])}", f"Fecha de radicación: {fmt_fecha(s['fecha_radicacion'])}",
        f"Fecha máxima de respuesta: {fmt_fecha(s['fecha_vencimiento'])}", f"Tipo: {s['tipo_nombre']}",
        f"Asunto: {s['asunto']}", f"Solicitante: {s.get('solicitante_nombre') or ''}", "",
        "Consulte el estado con su radicado y código en la página «Consultar estado»."])


def mostrar_acuse(res: dict):
    s = res["solicitud"]
    st.success("✅ ¡Listo! Su solicitud quedó radicada.")
    c1, c2, c3 = st.columns(3)
    c1.metric("Número de radicado", s["radicado"])
    c2.metric("Código de consulta", res["codigo"])
    c3.metric("Respuesta a más tardar", fmt_fecha(s["fecha_vencimiento"]))
    st.markdown(f"Guarde el **radicado** y el **código**: los necesita para consultar el estado. "
                f"Se radicó el **{fmt_fecha(s['fecha_radicacion'])}** "
                "(lo recibido después de la hora de corte o en un día no hábil cuenta desde el siguiente día hábil).")
    if res.get("acuse"):
        if res["acuse"]["estado"] == "simulado":
            st.warning(f"📧 CORREO SIMULADO: este prototipo no envió un correo real a {s.get('solicitante_email')}. "
                       "Guarde el número de radicado y el código de consulta, o descargue el acuse en PDF.")
        else:
            st.caption(f"📧 Acuse enviado a {s.get('solicitante_email')} ({res['acuse']['estado']}).")
    elif s.get("solicitante_email") is None:
        st.caption("No se envió acuse por correo porque no indicó un correo electrónico.")
    if res.get("duplicado_de"):
        st.warning(f"Parece una solicitud parecida a la {res['duplicado_de']}. El equipo revisará si es la misma.")
    for r in res.get("rechazados") or []:
        st.warning(r)
    st.download_button("🖨️ Descargar acuse (PDF)", acuse_pdf(res), f"acuse-{s['radicado']}.pdf", mime="application/pdf")


def formulario_radicacion(usuario: dict | None = None, empresa_fija: dict | None = None, clave: str = "rad"):
    """Máximo 8 campos obligatorios (RU-01). Devuelve el resultado de la radicación o None."""
    interno = usuario is not None
    tipos = C.tipos()
    if f"{clave}-res" in st.session_state:
        mostrar_acuse(st.session_state[f"{clave}-res"])
        if st.button("Radicar otra solicitud", key=f"{clave}-otra"):
            del st.session_state[f"{clave}-res"]
            st.rerun()
        return st.session_state[f"{clave}-res"]
    emp = empresa_fija
    if not emp:
        opciones = [e for e in C.empresas() if not interno or usuario["rol"] == "admin" or e["id"] in usuario["empresas"]]
        emp = st.selectbox("Empresa a la que dirige su solicitud *", opciones, index=None, key=f"{clave}-emp",
                           format_func=lambda e: e["nombre"], placeholder="Elija la empresa")
    canal = "web"
    if interno:
        canal = st.radio("Canal de recepción *", ["presencial", "telefonico", "correo"], horizontal=True, key=f"{clave}-canal",
                         format_func=lambda c: C.CANALES[c])
    tipo = st.radio("¿Qué desea hacer? *", tipos, key=f"{clave}-tipo", index=None,
                    format_func=lambda t: t["nombre"], captions=[f"{t['descripcion']} {t['ejemplo']}" for t in tipos])
    temas = C.temas(emp["id"]) if emp else []
    with st.form(f"{clave}-form", clear_on_submit=False, border=True):
        tema = st.selectbox("Tema (opcional)", [None] + temas, format_func=lambda t: "No sé / otro" if t is None else t["nombre"])
        asunto = st.text_input("Asunto (una frase corta) *", max_chars=150, placeholder="Ej.: Cobro doble en la factura de agosto")
        descripcion = st.text_area("Cuéntenos qué pasó y qué solicita *", height=140, max_chars=5000)
        anonimo = False
        if emp and emp.get("acepta_anonimas") and tipo and tipo["codigo"] == "Q":
            anonimo = st.checkbox("Quiero presentar esta queja de forma anónima (no recibirá respuesta por correo)")
        c1, c2 = st.columns(2)
        nombre = c1.text_input("Nombre completo *" if not anonimo else "Nombre (opcional)", autocomplete="name")
        email = c2.text_input("Correo electrónico *" if canal == "web" and not anonimo else "Correo electrónico (opcional)",
                              autocomplete="email")
        c3, c4, c5 = st.columns(3)
        tipo_doc = c3.selectbox("Tipo de documento (opcional)", ["CC", "CE", "TI", "PA", "NIT"])
        num_doc = c4.text_input("Número de documento (opcional)")
        telefono = c5.text_input("Teléfono (opcional)", autocomplete="tel")
        docs_fisicos, hojas = False, 0
        if interno:
            docs_fisicos = st.checkbox("📄 El ciudadano entregó documentos en papel (quedarán en el archivo físico)")
            hojas = st.number_input("Número de hojas entregadas (solo si marcó la casilla)", min_value=0, max_value=500, value=0,
                                    help="Se usa para numerar los folios del expediente.")
        archivos = st.file_uploader(f"Adjuntos (opcional): PDF, DOCX, XLSX, JPG, PNG o EML · máx. {C.param_num('max_mb_archivo', 10):g} MB c/u "
                                    f"y {C.param_num('max_mb_solicitud', 25):g} MB en total",
                                    type=["pdf", "docx", "xlsx", "jpg", "jpeg", "png", "eml"], accept_multiple_files=True)
        autoriza = st.checkbox("Autorizo el tratamiento de mis datos personales para gestionar esta solicitud, según la "
                               "Ley 1581 de 2012 y la política de tratamiento de datos de la empresa. *"
                               if not interno else "El ciudadano autorizó el tratamiento de sus datos (Ley 1581 de 2012).")
        st.caption("* Campo obligatorio. Prototipo beta: escriba solo datos ficticios.")
        enviar = st.form_submit_button("Enviar solicitud" if not interno else "Radicar", type="primary")
    if enviar:
        if not emp or not tipo:
            st.error("⚠️ Elija la empresa y el tipo de solicitud antes de enviar.")
            return None
        try:
            res = S.radicar({"empresa_id": emp["id"], "tipo_id": tipo["id"], "tema_id": tema["id"] if tema else None,
                             "asunto": asunto, "descripcion": descripcion, "nombre": nombre, "email": email,
                             "tipo_doc": tipo_doc, "num_doc": num_doc, "telefono": telefono, "anonimo": anonimo,
                             "autoriza_datos": autoriza, "docs_fisicos": docs_fisicos, "hojas_fisicas": int(hojas or 0)},
                            canal=canal, usuario=usuario,
                            archivos=[(a.name, a.getvalue(), a.type) for a in (archivos or [])])
            st.session_state[f"{clave}-res"] = res
            st.rerun()
        except Exception as e:
            ui.error(e)
    return None
