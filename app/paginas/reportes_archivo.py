"""Reportes de archivo: retenciones por vencer (30/90 días), ocupación de cajas y PQRS cerradas sin serie."""
import pandas as pd
import plotly.express as px
import streamlit as st

import tema
import ui
import ui_archivo as UA
from core import archivo as A
from core.reloj import fmt_fecha

ui.aviso_beta()
u = ui.requiere("archivista", "admin", "supervisor", "director", "auditor")
tema.hero("Reportes de archivo", "Retenciones por vencer, ocupación de cajas y casos cerrados sin serie. Descargables en Excel y CSV.", "📊")
emp = UA.selector_empresa(u, "rep_emp")
exps = [x for x in A.expedientes(u, emp["id"]) if x["estado"] != "dispuesto"]
t = st.tabs(["⏰ Retenciones por vencer", "📦 Ocupación de cajas", "🧾 Cerradas sin serie"])

with t[0]:
    dias = st.radio("Horizonte", [30, 90], index=1, horizontal=True, format_func=lambda d: f"Próximos {d} días (y vencidas)", key="rep_dias")
    filas = sorted([x for x in exps if x["dias_restantes"] is not None and x["dias_restantes"] <= dias], key=lambda x: x["dias_restantes"])
    c1, c2 = st.columns([3, 2])
    if not filas:
        tema.vacio("🟢", "Nada por vencer en ese horizonte", "")
    else:
        df = UA.df_expedientes(filas)[["Alerta", "Radicado", "Serie", "Vence retención", "Días", "Disposición", "Folios", "Ubicación"]]
        c1.dataframe(df, hide_index=True, width="stretch", height=min(38 * (len(df) + 1) + 3, 420))
        conteo = pd.Series([x["nivel_texto"] for x in filas]).value_counts().rename_axis("Nivel").reset_index(name="Expedientes")
        fig = px.pie(conteo, names="Nivel", values="Expedientes", hole=.5, color="Nivel",
                     color_discrete_map={"Vencida": "#DC2626", "≤ 30 días": "#EA580C", "≤ 90 días": "#CA8A04"})
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=300)
        c2.plotly_chart(fig, width="stretch")
        ui.df_descarga(df, f"retenciones_{dias}d_{emp['codigo']}", "rep1")

with t[1]:
    cajas = A.cajas(u, emp["id"])
    if not cajas:
        tema.vacio("📦", "Sin cajas registradas", "")
    else:
        df = pd.DataFrame([{"Caja": c["codigo"], "Ubicación": c["ubicacion"], "Carpetas": c["n_carpetas"], "Capacidad": c["capacidad_carpetas"],
                            "Ocupación %": c["ocupacion"], "Libres": c["capacidad_carpetas"] - c["n_carpetas"], "Estado": c["estado"]} for c in cajas])
        c1, c2 = st.columns([3, 2])
        c1.dataframe(df, hide_index=True, width="stretch", height=min(38 * (len(df) + 1) + 3, 420),
                     column_config={"Ocupación %": st.column_config.ProgressColumn("Ocupación %", min_value=0, max_value=100, format="%.0f %%")})
        fig = px.bar(df, x="Caja", y="Ocupación %", range_y=[0, 100], color="Ocupación %", color_continuous_scale=["#16A34A", "#CA8A04", "#DC2626"])
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=300, coloraxis_showscale=False)
        c2.plotly_chart(fig, width="stretch")
        ui.df_descarga(df, f"ocupacion_cajas_{emp['codigo']}", "rep2")

with t[2]:
    ss = A.cerradas_sin_serie(u, emp["id"])
    if not ss:
        tema.vacio("✅", "No hay casos cerrados sin serie", "Todo lo cerrado ya tiene su expediente.")
    else:
        df = pd.DataFrame([{"Radicado": s["radicado"], "Tipo": s["tipo_nombre"], "Asunto": s["asunto"], "Cierre": fmt_fecha(s["fecha_respuesta"]) if s["fecha_respuesta"] else "—",
                            "Papel": f"{s['hojas_fisicas'] or ''} hojas" if s["docs_fisicos"] else "Solo electrónico"} for s in ss])
        st.warning(f"{len(ss)} PQRS cerradas aún no tienen serie TRD: no se puede calcular su retención.")
        st.dataframe(df, hide_index=True, width="stretch", height=min(38 * (len(df) + 1) + 3, 420))
        ui.df_descarga(df, f"cerradas_sin_serie_{emp['codigo']}", "rep3")
