"""Archivo físico: cajas, carpetas, folios, ubicación, ocupación y rótulos con QR real."""
import pandas as pd
import streamlit as st

import tema
import ui
import ui_archivo as UA
from core import archivo as A

ui.aviso_beta()
if not ui.usuario():  # QR escaneado sin sesión: se recuerda la caja y se pide ingresar (al entrar se abre sola)
    if str(st.query_params.get("codigo", "")).strip():
        st.session_state["destino_qr"] = str(st.query_params.get("codigo")).strip()
    st.switch_page(ui.PAGINAS["ingresar"])
u = ui.requiere("archivista", "admin", "supervisor", "director", "auditor", "abogado")
tema.hero("Cajas, carpetas y rótulos", "Dónde está cada papel: estante, caja, carpeta y folios. Rótulos listos para imprimir con QR.", "📦",
          ["Ocupación de cajas", "QR real"])
emp = UA.selector_empresa(u, "caj_emp")
UA.mostrar_flash()
cajas = A.cajas(u, emp["id"])
carpetas = A.carpetas(u, emp["id"])

# --- Llegada desde el QR de un rótulo: ?codigo=EMP01-C-001  (o ...-F01)
codigo = str(st.query_params.get("codigo", "")).strip()
if not codigo and st.session_state.get("destino_qr"):  # llegó al QR sin sesión, ingresó y se conservó el destino
    codigo = st.session_state.pop("destino_qr")
    st.query_params["codigo"] = codigo
st.session_state.pop("destino_qr", None)
if codigo:
    caja = next((c for c in cajas if c["codigo"] == codigo), None)
    carp = next((f for f in carpetas if f["codigo"] == codigo), None)
    if caja or carp:
        o = caja or carp
        st.success(f"📲 Abierto desde el QR: **{codigo}**")
        if caja:
            tema.tarjeta(f"📦 Caja {caja['codigo']}", f"<div>{tema.esc(caja['ubicacion'])}</div><div>{caja['n_carpetas']} de {caja['capacidad_carpetas']} carpetas · "
                         f"estado: {tema.esc(caja['estado'])}</div>")
        else:
            tema.tarjeta(f"📁 Carpeta {carp['codigo']}", f"<div>{tema.esc(carp['ubicacion'])}</div><div>Serie {tema.esc(carp['serie_codigo'] or '—')} · folios "
                         f"{carp['folio_inicial']}–{carp['folio_final']} · {carp['n_expedientes']} expediente(s) · estado: {tema.esc(carp['estado'])}</div>")
        if st.button("Quitar el filtro del QR", key="qr_quitar"):
            st.query_params.pop("codigo", None)
            st.rerun()
    else:
        st.warning(f"No se encontró «{codigo}» en {emp['codigo']}. Verifique que eligió la empresa correcta.")

ocup = round(100 * sum(c["n_carpetas"] for c in cajas) / max(1, sum(c["capacidad_carpetas"] for c in cajas)), 1) if cajas else 0
tema.kpis([("📦", "Cajas", len(cajas), "azul", f"{sum(1 for c in cajas if c['estado'] == 'cerrada')} cerradas"),
           ("📁", "Carpetas", len(carpetas), "teal", f"{sum(f['folios'] for f in carpetas)} folios de papel"),
           ("📊", "Ocupación", f"{ocup} %", "verde" if ocup < 70 else ("amarillo" if ocup < 90 else "rojo"), "Carpetas / capacidad"),
           ("🔄", "Carpetas prestadas", sum(1 for f in carpetas if f["estado"] == "prestada"), "morado", "Fuera del archivo")])

pestanas = ["📦 Cajas y ocupación", "📁 Carpetas", "🏷️ Rótulos y QR"] + (["➕ Registrar"] if u["rol"] in A.ROLES_GESTION else [])
tabs = st.tabs(pestanas)

with tabs[0]:
    if not cajas:
        tema.vacio("📦", "Aún no hay cajas", "El archivista registra la primera caja en la pestaña «Registrar».")
    for c in cajas:
        cols = st.columns([3, 5, 2])
        cols[0].markdown(f"**📦 {c['codigo']}**  \n" + tema.badge(c["estado"].upper(), "gris" if c["estado"] == "cerrada" else "verde"), unsafe_allow_html=True)
        cols[1].markdown(f"{tema.esc(c['ubicacion'])}" + tema.barra(c["ocupacion"], "auto"), unsafe_allow_html=True)
        cols[2].markdown(f"**{c['n_carpetas']} / {c['capacidad_carpetas']}** carpetas  \n{c['ocupacion']} % ocupada")
    if cajas:
        df = pd.DataFrame([{"Caja": c["codigo"], "Sede": c["sede"], "Depósito": c["deposito"], "Estante": c["estante"], "Entrepaño": c["entrepano"],
                            "Carpetas": c["n_carpetas"], "Capacidad": c["capacidad_carpetas"], "Ocupación %": c["ocupacion"], "Estado": c["estado"]} for c in cajas])
        with st.expander("Ver como tabla / descargar"):
            st.dataframe(df, hide_index=True, width="stretch")
            ui.df_descarga(df, f"cajas_{emp['codigo']}", "caj")

with tabs[1]:
    if not carpetas:
        tema.vacio("📁", "Aún no hay carpetas", "Las carpetas se crean dentro de una caja.")
    else:
        df = pd.DataFrame([{"Carpeta": f["codigo"], "Caja": f["caja_codigo"], "Serie": f"{f['serie_codigo'] or '—'} {f['serie_nombre'] or ''}".strip(),
                            "Año": f["anio"], "Folios": f"{f['folio_inicial']}–{f['folio_final']}" if f["n_expedientes"] else "—",
                            "Expedientes": f["n_expedientes"], "Estante / entrepaño": f"{f['estante']} / {f['entrepano']}", "Estado": f["estado"]} for f in carpetas])
        st.dataframe(df, hide_index=True, width="stretch", height=min(38 * (len(df) + 1) + 3, 460))
        ui.df_descarga(df, f"carpetas_{emp['codigo']}", "carp")

with tabs[2]:
    st.markdown("Elija una caja o una carpeta: el rótulo trae un **QR real** que lleva a su ficha en el sistema (el usuario debe iniciar sesión).")
    objetos = [("caja", c) for c in cajas] + [("carpeta", f) for f in carpetas]
    if not objetos:
        tema.vacio("🏷️", "Nada que rotular todavía", "Registre cajas y carpetas primero.")
    else:
        sel = st.selectbox("¿Qué desea rotular?", objetos, key="rot_obj",
                           format_func=lambda o: f"{'📦 Caja' if o[0] == 'caja' else '📁 Carpeta'} · {o[1]['codigo']}")
        tipo, obj = sel
        c1, c2 = st.columns([1, 2])
        with c1, st.container(border=True):
            st.image(A.qr_png(A.payload_qr(tipo, obj["codigo"]), 6), caption=f"QR de {obj['codigo']}", width=230)
        with c2:
            st.markdown(f"**Contenido del QR:** `{A.payload_qr(tipo, obj['codigo'])}`")
            st.markdown(f"**Ubicación:** {obj['ubicacion']}")
            st.download_button("🖨️ Descargar rótulo (PDF)", A.rotulo_pdf(tipo, obj), f"rotulo_{obj['codigo']}.pdf", mime="application/pdf",
                               key="rot_pdf", type="primary")
            if tipo == "caja":
                st.download_button("🖨️ Rótulos de la caja y de todas sus carpetas (PDF)", A.rotulos_caja_pdf(obj, u),
                                   f"rotulos_{obj['codigo']}.pdf", mime="application/pdf", key="rot_pdf_todos")
            st.caption("Tamaño A6 horizontal. En la demostración el QR apunta a la dirección de esta aplicación.")

if u["rol"] in A.ROLES_GESTION:
    with tabs[3]:
        a, b = st.columns(2)
        with a:
            st.markdown("#### 📦 Nueva caja")
            with st.form("caja_form", clear_on_submit=True):
                c1, c2 = st.columns(2)
                sede = c1.text_input("Sede*", value="Sede principal")
                dep = c2.text_input("Depósito*", value="Archivo central")
                c3, c4, c5 = st.columns(3)
                est = c3.text_input("Estante*", placeholder="Ej.: E-04")
                ent = c4.text_input("Entrepaño*", placeholder="Ej.: 2")
                cap = c5.number_input("Capacidad (carpetas)", 1, 200, 20)
                obs = st.text_input("Observaciones")
                if st.form_submit_button("➕ Registrar caja", type="primary"):
                    if UA.ejecutar(A.crear_caja, "Caja registrada.", {"empresa_id": emp["id"], "sede": sede, "deposito": dep, "estante": est,
                                                                      "entrepano": ent, "capacidad_carpetas": cap, "observaciones": obs}, u):
                        st.rerun()
        with b:
            st.markdown("#### 📁 Nueva carpeta")
            abiertas = [c for c in cajas if c["estado"] == "abierta" and c["n_carpetas"] < c["capacidad_carpetas"]]
            if not abiertas:
                st.info("No hay cajas abiertas con espacio. Registre una caja nueva.")
            else:
                with st.form("carp_form", clear_on_submit=True):
                    caja_sel = st.selectbox("Caja", abiertas, format_func=lambda c: f"{c['codigo']} ({c['n_carpetas']}/{c['capacidad_carpetas']})")
                    ser = st.selectbox("Serie", [None] + A.series_asignables(u, emp["id"]),
                                       format_func=lambda s: "— Se define con el primer expediente —" if s is None else f"{s['codigo']} · {s['nombre']}")
                    anio = st.number_input("Año", 2000, 2100, 2026)
                    desc = st.text_input("Descripción")
                    if st.form_submit_button("➕ Crear carpeta", type="primary"):
                        if UA.ejecutar(A.crear_carpeta, "Carpeta creada.", caja_sel["id"], u, ser["id"] if ser else None, int(anio), desc):
                            st.rerun()
        st.markdown("#### 🔒 Cerrar una caja")
        llenas = [c for c in cajas if c["estado"] == "abierta"]
        if llenas:
            c1, c2 = st.columns([3, 1])
            cc = c1.selectbox("Caja a cerrar (ya no recibe carpetas)", llenas, key="cerrar_sel", format_func=lambda c: f"{c['codigo']} ({c['n_carpetas']}/{c['capacidad_carpetas']})")
            if c2.button("Cerrar caja", key="cerrar_btn"):
                if UA.ejecutar(A.cerrar_caja, "Caja cerrada.", cc["id"], u):
                    st.rerun()
        st.caption("Para guardar un expediente en una carpeta use **Expedientes → Guardar el papel en una carpeta**.")
