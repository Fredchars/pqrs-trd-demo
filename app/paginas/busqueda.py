"""Búsqueda por filtros combinables y por texto completo (solicitudes, respuestas y documentos)."""
from datetime import date

import streamlit as st

import ui
from core import consultas as C
from core import flujo
from core import servicios as S
from core.reportes import listado

ui.aviso_beta()
u = ui.requiere()
st.title("🔍 Búsqueda")
st.caption("Busque por palabras (también dentro de PDF y DOCX adjuntos, sin importar tildes), por número de radicado o "
           "por documento de identidad. Solo verá los casos que su rol le permite ver.")

guardados = S.filtros_guardados(u)
if guardados:
    g = st.selectbox("Filtros guardados", [None] + guardados, format_func=lambda x: "—" if x is None else x["nombre"])
    if g and st.button("Aplicar filtro guardado"):
        st.session_state["filtro_busq"] = g["filtros"]
        st.rerun()
pre = st.session_state.get("filtro_busq", {})

texto = st.text_input("Palabras, radicado o documento", value=pre.get("texto", ""),
                      placeholder="Ej.: cobro doble · EMP01-2026-R-000012 · hidrometro")
with st.expander("Filtros", expanded=bool(pre)):
    c1, c2, c3, c4 = st.columns(4)
    emps = C.empresas() if u["rol"] in ("admin", "auditor") else [C.empresa(e) for e in u["empresas"]]
    f_emp = c1.multiselect("Empresa", emps, format_func=lambda e: e["codigo"],
                           default=[e for e in emps if e["id"] in pre.get("empresa_id", [])])
    tps = C.tipos(False)
    f_tipo = c2.multiselect("Tipo", tps, format_func=lambda t: t["nombre"], default=[t for t in tps if t["id"] in pre.get("tipo_id", [])])
    f_est = c3.multiselect("Estado", list(flujo.ESTADOS), default=pre.get("estado", []))
    f_canal = c4.multiselect("Canal", list(C.CANALES), format_func=lambda c: C.CANALES[c], default=pre.get("canal", []))
    c5, c6, c7, c8 = st.columns(4)
    f_sem = c5.multiselect("Semáforo", ["verde", "amarillo", "rojo", "negro", "pausa", "cerrado"], default=pre.get("semaforo", []))
    abogs = [a for a in C.usuarios("abogado") if not f_emp or set(a["empresas"]) & {e["id"] for e in f_emp}]
    f_ab = c6.multiselect("Abogado", abogs, format_func=lambda a: a["nombre"], default=[a for a in abogs if a["id"] in pre.get("abogado_id", [])])
    aprob = C.usuarios("supervisor") + C.usuarios("director")
    f_apr = c7.selectbox("Aprobador", [None] + aprob, format_func=lambda a: "—" if a is None else a["nombre"])
    f_sol = c8.text_input("Solicitante (nombre, correo o documento)", value=pre.get("solicitante", ""))
    c9, c10, c11 = st.columns(3)
    rango_rec = c9.date_input("Recepción entre", value=(), format="DD/MM/YYYY")
    rango_ven = c10.date_input("Vencimiento entre", value=(), format="DD/MM/YYYY")
    rango_res = c11.date_input("Respuesta entre", value=(), format="DD/MM/YYYY")
    m1, m2, m3, m4 = st.columns(4)
    f_pro = m1.checkbox("Prorrogadas", value=pre.get("prorrogada", False))
    f_par = m2.checkbox("Con respuesta parcial", value=pre.get("respuesta_parcial", False))
    f_rea = m3.checkbox("Reabiertas", value=pre.get("reabierta", False))
    f_dup = m4.checkbox("Posibles duplicados", value=pre.get("revisar_duplicado", False))

filtros = {"empresa_id": [e["id"] for e in f_emp], "tipo_id": [t["id"] for t in f_tipo], "estado": f_est, "canal": f_canal,
           "semaforo": f_sem, "abogado_id": [a["id"] for a in f_ab], "solicitante": f_sol, "prorrogada": f_pro,
           "respuesta_parcial": f_par, "reabierta": f_rea, "revisar_duplicado": f_dup}
if f_apr:
    filtros["aprobador_id"] = f_apr["id"]
for nombre, rango in (("recepcion", rango_rec), ("vencimiento", rango_ven), ("respuesta", rango_res)):
    if isinstance(rango, tuple) and len(rango) == 2:
        filtros[f"{nombre}_desde"], filtros[f"{nombre}_hasta"] = rango

import time
t0 = time.time()
res = C.buscar(u, texto, filtros)
st.caption(f"{len(res)} resultado(s) en {time.time() - t0:.2f} s" + (" · ordenados por relevancia" if texto else ""))
if texto and res and res[0].get("fragmento"):
    with st.expander("Dónde aparece la coincidencia", expanded=True):
        for s in res[:10]:
            st.markdown(f"**{s['radicado']}** · _{s.get('coincidencia_en')}_: …{s.get('fragmento')}…")
ui.tabla_casos(res, "busq", {"coincidencia_en": "Coincidencia en"} if texto else None)
if res:
    ui.df_descarga(listado(res), "busqueda_pqrs", "busq-dl")
with st.popover("💾 Guardar este filtro"):
    nombre = st.text_input("Nombre del filtro", placeholder="Mis casos rojos")
    if st.button("Guardar"):
        try:
            serial = {k: v for k, v in filtros.items() if not isinstance(v, date) and v not in ([], "", False, None)}
            serial["texto"] = texto
            S.guardar_filtro(u, nombre, serial)
            st.success("Filtro guardado.")
        except Exception as e:
            ui.error(e)
