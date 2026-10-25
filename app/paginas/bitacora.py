"""Bitácora de auditoría (inmutable): toda acción queda registrada con usuario, origen y fecha."""
import json

import pandas as pd
import streamlit as st

import ui
from core import consultas as C
from core.reloj import fmt_fechahora

ui.aviso_beta()
u = ui.requiere("admin", "auditor")
st.title("📜 Bitácora de auditoría")
st.caption("La bitácora no se puede modificar ni borrar (la base de datos lo impide). Origen: app, correo, api, mcp, sistema.")
c0, c1, c2, c3 = st.columns(4)
por_etiqueta = {"Todas las empresas": None, "Sin empresa (sistema)": C.SIN_EMPRESA,
                **{f"{e['codigo']} · {e['nombre']}": e["id"] for e in C.empresas()}}
etiqueta = {v: k for k, v in por_etiqueta.items()}
f_emp = por_etiqueta[c0.selectbox("Empresa", list(por_etiqueta))]
lim = c1.selectbox("Últimos", [200, 500, 2000], index=1)
evs = C.eventos(None, lim, empresa_id=f_emp)
origenes = sorted({e["origen"] for e in evs})
f_or = c2.multiselect("Origen", origenes)
acciones = sorted({e["accion"] for e in evs})
f_ac = c3.multiselect("Acción", acciones)
txt = st.text_input("Contiene (radicado, usuario o detalle)")
filas = []
for e in evs:
    if f_or and e["origen"] not in f_or or f_ac and e["accion"] not in f_ac:
        continue
    det = json.dumps(e["detalle"] or {}, ensure_ascii=False)
    fila = {"#": e["id"], "Fecha": fmt_fechahora(e["fecha"]), "Radicado": e.get("radicado") or "", "Acción": e["accion"],
            "Empresa": etiqueta.get(e.get("empresa_id"), "—") if e.get("empresa_id") else "—",
            "Usuario": e.get("usuario") or "", "Origen": e["origen"], "Detalle": det}
    if txt and txt.lower() not in " ".join(str(v) for v in fila.values()).lower():
        continue
    filas.append(fila)
df = pd.DataFrame(filas)
st.caption(f"{len(df)} eventos")
st.dataframe(df, hide_index=True, width="stretch", height=560)
if not df.empty:
    ui.df_descarga(df, "bitacora", "bit")
