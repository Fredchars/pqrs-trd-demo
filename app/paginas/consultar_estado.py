"""Consulta pública del estado con radicado + código; aporte de información y encuesta."""
import streamlit as st

import ui
from core import consultas as C
from core import flujo
from core import servicios as S
from core.reloj import fmt_fecha

ui.aviso_beta()
st.title("🔎 Consulte el estado de su solicitud")
st.caption("Use el número de radicado y el código que recibió en el acuse. "
           "Casos precargados de la demo: código **DEMO2026**.")
with st.form("form_consulta"):
    c1, c2 = st.columns(2)
    radicado = c1.text_input("Número de radicado", value=str(st.query_params.get("radicado", "")),
                             placeholder="EMP01-2026-R-000123")
    codigo = c2.text_input("Código de consulta", type="password")
    ok = st.form_submit_button("Consultar", type="primary")
if ok:
    try:
        st.session_state["consulta_activa"] = (radicado.strip().upper(), codigo.strip().upper())
        S.consultar_estado(*st.session_state["consulta_activa"])
    except Exception as e:
        st.session_state.pop("consulta_activa", None)
        ui.error(e)

if "consulta_activa" in st.session_state:
    try:
        r = S.consultar_estado(*st.session_state["consulta_activa"])
    except Exception as e:
        ui.error(e)
        st.stop()
    s = r["solicitud"]
    ui.encabezado_empresa(C.empresa(s["empresa_id"]), f"Radicado {s['radicado']}")
    st.markdown(f"### Estado: {flujo.explicar(s['estado'])}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Tipo", s["tipo_nombre"])
    c2.metric("Radicada el", fmt_fecha(s["fecha_radicacion"]))
    c3.metric("Respuesta a más tardar", fmt_fecha(s["fecha_vencimiento"]))
    if s.get("prorrogada"):
        st.info("El plazo de respuesta fue ampliado (prórroga). Le enviamos el motivo por correo.")
    if s["estado"] == "PENDIENTE_INFO":
        st.warning("Necesitamos información adicional para responder. Mientras tanto el plazo está suspendido.")
        with st.form("aporte"):
            texto = st.text_area("Escriba la información solicitada")
            arch = st.file_uploader(f"Adjuntos (opcional) · máx. {C.param_num('max_mb_archivo', 10):g} MB c/u", type=["pdf", "docx", "xlsx", "jpg", "jpeg", "png"],
                                    accept_multiple_files=True)
            if st.form_submit_button("Enviar información", type="primary"):
                try:
                    S.aportar_informacion(s["id"], texto, [(a.name, a.getvalue(), a.type) for a in arch or []])
                    st.success("¡Gracias! Recibimos la información y el plazo se reanudó.")
                    st.rerun()
                except Exception as e:
                    ui.error(e)
    if r["respuesta"]:
        st.markdown("### Respuesta" + (" parcial" if r["respuesta"]["es_parcial"] else ""))
        st.markdown(f"<div class='caja'>{r['respuesta']['contenido'].replace(chr(10), '<br>')}</div>", unsafe_allow_html=True)
        if r["pdf"]:
            try:
                datos, d, integro = S.descargar(r["pdf"]["id"])
                st.download_button("⬇️ Descargar respuesta en PDF", datos, d["nombre_original"], mime="application/pdf")
                st.caption(f"Huella SHA-256 del documento: `{d['sha256'][:16]}…` · {'✔ íntegro' if integro else '⚠ no coincide'}")
            except Exception:
                st.caption("El PDF no está disponible en este momento.")
        if C.param_si("encuesta_activa", True) and not r["encuesta"] and s["estado"] in ("ENVIADA", "CERRADA"):
            with st.form("encuesta"):
                st.markdown("**¿Qué tan satisfecho(a) está con la respuesta?** (opcional)")
                p = st.radio("Puntaje", [5, 4, 3, 2, 1], horizontal=True,
                             format_func=lambda x: {5: "5 · Muy satisfecho", 4: "4", 3: "3", 2: "2", 1: "1 · Nada satisfecho"}[x])
                com = st.text_input("Comentario (opcional)")
                if st.form_submit_button("Enviar opinión"):
                    try:
                        S.registrar_encuesta(s["id"], p, com)
                        st.success("¡Gracias por su opinión!")
                    except Exception as e:
                        ui.error(e)
