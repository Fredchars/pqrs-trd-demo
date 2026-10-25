"""Buzón de correo: enviados (acuses, respuestas, alertas), recibidos, cuarentena y simulación de correos del ciudadano."""
import pandas as pd
import streamlit as st

import ui
from core import consultas as C
from core import correo
from core import servicios as S
from core.reloj import fmt_fechahora
from core.repositorio import obtener_repo

ui.aviso_beta()
u = ui.requiere("radicador", "supervisor", "admin")
st.title("✉️ Buzón de correo")
modo = correo.modo()
if modo == "real":
    st.caption("Modo **real** (IMAP/SMTP configurado en los secretos).")
else:
    st.warning(correo.AVISO_SIMULADO)
    st.caption("También puede simular que un ciudadano escribe al buzón.")

t1, t2, t3, t4 = st.tabs(["📨 Simular correo del ciudadano", "📥 Recibidos", "🚫 Cuarentena", "📤 Enviados"])
with t1:
    visibles = C.empresas_alcance(u)
    emps = [e for e in C.empresas() if visibles is None or e["id"] in visibles]
    with st.form("sim", clear_on_submit=False):
        c1, c2 = st.columns(2)
        de = c1.text_input("De (correo ficticio del ciudadano)", "ciudadano.prueba@correo.example.com")
        emp = c2.selectbox("Para (buzón de la empresa)", emps, format_func=lambda e: f"{e['buzon_correo']} · {e['codigo']}")
        asunto = st.text_input("Asunto", "Queja por cobro doble en la factura de agosto",
                               help="Si incluye un número de radicado (p. ej. EMP01-2026-Q-000012) el correo se agrega a ese expediente.")
        cuerpo = st.text_area("Mensaje", "Buenos días. Me llegó cobrado dos veces el mismo servicio. Adjunto la factura. Gracias.")
        adj = st.file_uploader("Adjuntos (opcional)", accept_multiple_files=True)
        c1, c2 = st.columns(2)
        dejar = c1.form_submit_button("Dejar en el buzón (lo procesará la tarea programada)")
        ya = c2.form_submit_button("Enviar y procesar ahora", type="primary")
    if dejar or ya:
        try:
            adjuntos = [(a.name, a.getvalue(), a.type or "application/octet-stream") for a in (adj or [])]
            cid = correo.simular_entrante(obtener_repo(), de, emp["buzon_correo"], asunto, cuerpo, adjuntos)
            if ya:
                res = S.leer_correo()
                for r in res:
                    if r.get("resultado") == "radicada":
                        st.success(f"Correo radicado como **{r['radicado']}** (tipo {r['tipo']}, {r['empresa']}). "
                                   "Se envió el acuse al ciudadano.")
                    elif r.get("resultado") == "agregado_a_expediente":
                        st.success(f"Correo agregado al expediente **{r['radicado']}**.")
                    elif r.get("resultado") == "cuarentena":
                        st.warning("El correo parece spam y quedó en cuarentena para revisión.")
                    else:
                        st.info(str(r))
            else:
                st.success(f"Correo #{cid} dejado en el buzón. Se procesará en la próxima ejecución de tareas.")
        except Exception as e:
            ui.error(e)
    st.caption("Ejemplos: «Petición de copia de contrato», «Denuncia anónima de fraude», «Respuesta al radicado "
               "EMP01-2026-P-000003», o un asunto con «gana dinero rápido» para probar la cuarentena.")


def tabla(filas, key):
    if not filas:
        st.info("No hay correos.")
        return
    df = pd.DataFrame([{"#": c["id"], "Fecha": fmt_fechahora(c["fecha"]), "De": c["de"], "Para": c["para"], "Asunto": c["asunto"],
                        "Estado": c["estado"], "Modo": c["modo"],
                        "Radicado": (C.obtener_solicitud(c["solicitud_id"], sin_alcance=True) or {}).get("radicado", "") if c.get("solicitud_id") else ""}
                       for c in filas])
    st.dataframe(df, hide_index=True, width="stretch", height=380)
    elegido = st.selectbox("Ver correo", filas, format_func=lambda c: f"#{c['id']} · {c['asunto']}", key=f"{key}-sel")
    if elegido:
        with st.container(border=True):
            st.markdown(f"**De:** {elegido['de']}  \n**Para:** {elegido['para']}  \n**Asunto:** {elegido['asunto']}")
            st.text(elegido["cuerpo"] or "")
            if elegido.get("error"):
                st.error(elegido["error"])
        return elegido


with t2:
    tabla([c for c in C.correos(u, "entrada") if c["estado"] != "cuarentena"], "rec")
    if st.button("Procesar correos pendientes ahora"):
        res = S.leer_correo()
        if u["rol"] == "admin":
            st.write(res)
        else:  # la tarea procesa todos los buzones; no se muestran radicados de otras empresas
            st.success(f"Se procesaron {len(res)} correo(s) pendientes.")
with t3:
    cuar = [c for c in C.correos(u, "entrada") if c["estado"] == "cuarentena"]
    sel = tabla(cuar, "cua")
    if sel and st.button("✅ No es spam: radicar este correo", type="primary"):
        try:
            r = S.liberar_cuarentena(sel["id"], u)
            st.success(f"Radicado: {r.get('radicado')}")
        except Exception as e:
            ui.error(e)
with t4:
    tabla(C.correos(u, "salida"), "env")
