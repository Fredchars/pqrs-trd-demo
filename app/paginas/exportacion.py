"""Exportación de los datos de una empresa (entrega a una autoridad, portabilidad): ZIP con manifiesto SHA-256."""
import streamlit as st

import ui
from core import consultas as C
from core import exportacion as X

ui.aviso_beta()
u = ui.requiere("admin", "auditor")
st.title("📦 Exportar datos de una empresa")
st.caption("Genera un paquete ZIP con las tablas de **una sola empresa** (filtradas por empresa), los archivos de sus expedientes "
           "y un manifiesto con el SHA-256 de cada archivo. La exportación queda registrada en la bitácora. "
           "Es separación lógica por empresa (modelo pool con RLS), no una base de datos independiente.")
emps = {f"{e['codigo']} · {e['nombre']}": e["codigo"] for e in C.empresas()}
etiqueta = st.selectbox("Empresa", list(emps))
con_archivos = st.checkbox("Incluir los archivos del expediente (PDF, anexos)", value=True)
if st.button("Preparar paquete", type="primary"):
    try:
        with st.spinner("Generando el paquete…"):
            nombre, datos, man = X.generar_bytes(emps[etiqueta], u, con_archivos)
        st.session_state["exportacion"] = (nombre, datos, man)
    except Exception as e:
        ui.error(e)
paq = st.session_state.get("exportacion")
if paq:
    nombre, datos, man = paq
    st.success(f"Paquete listo: **{nombre}** ({len(datos) / 1024:.0f} KB).")
    st.download_button("⬇️ Descargar ZIP", datos, nombre, mime="application/zip", key="exp-zip")
    st.code(f"SHA-256 del manifiesto: {man['sha256_manifiesto']}")
    with st.expander("Contenido del paquete"):
        st.dataframe([{"Tabla": t["tabla"], "Filas": t["filas"], "SHA-256": t["sha256"][:16] + "…"}
                      for t in man["tablas"] if not t["global"]], hide_index=True, width="stretch")
        st.write(f"Archivos del expediente: **{len(man['archivos'])}** · faltantes: {len(man['archivos_faltantes_en_almacen'])} · "
                 f"con hash distinto al registrado: {man['verificaciones']['archivos_con_hash_distinto_al_registrado']}")
        for a in man["avisos"]:
            st.caption("• " + a)
