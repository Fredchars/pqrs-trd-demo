"""Reportes R1–R7 y R9 (R8 está en el detalle de cada caso). Exportables a Excel y CSV."""
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

import ui
from core import consultas as C
from core import reportes as RP
from core.reloj import hoy

ui.aviso_beta()
u = ui.requiere("abogado", "supervisor", "director", "admin", "auditor")
st.title("📊 Reportes e indicadores")
st.caption("Los datos se calculan sobre las solicitudes que su rol puede ver (el abogado solo ve las suyas).")

c1, c2, c3 = st.columns([2, 2, 3])
desde = c1.date_input("Recibidas desde", hoy() - timedelta(days=180), format="DD/MM/YYYY")
hasta = c2.date_input("Hasta", hoy(), format="DD/MM/YYYY")
emps = C.empresas() if u["rol"] in ("admin", "auditor") else [C.empresa(e) for e in u["empresas"]]
f_emp = c3.multiselect("Empresas (vacío = todas las que puede ver)", emps, format_func=lambda e: e["codigo"])
filtros = {"recepcion_desde": desde, "recepcion_hasta": hasta, "empresa_id": [e["id"] for e in f_emp]}
filas = C.listar_solicitudes(u, filtros)
df = RP.marco(filas)
if df.empty:
    st.info("No hay solicitudes en el periodo elegido.")
    st.stop()
sids = set(df["id"])

t = st.tabs(["R1 Tablero", "R2 Tipo y canal", "R3 Desempeño", "R4 Vencimientos", "R5 Cuellos de botella",
             "R6 Temas", "R7 Satisfacción", "R9 Informe periódico"])
with t[0]:
    r1 = RP.r1_tablero(df)
    cons = r1[r1["Empresa"] == "CONSOLIDADO"].iloc[0]
    m = st.columns(6)
    m[0].metric("Recibidas", int(cons["Recibidas"]))
    m[1].metric("Abiertas", int(cons["Abiertas"]))
    m[2].metric("Respondidas", int(cons["Respondidas"]))
    m[3].metric("% a tiempo", f"{cons['% a tiempo']} %")
    m[4].metric("Vencidas", int(cons["Vencidas"]))
    m[5].metric("Promedio (días hábiles)", cons["Promedio días hábiles"])
    st.dataframe(r1, hide_index=True, width="stretch")
    st.plotly_chart(px.bar(r1[r1["Empresa"] != "CONSOLIDADO"], x="Empresa", y=["Abiertas", "Respondidas", "Vencidas"],
                           barmode="group", title="Solicitudes por empresa"), width="stretch")
    ui.df_descarga(r1, "R1_tablero", "r1")
with t[1]:
    pt, pc = RP.r2_tipo_canal(df)
    st.markdown("**Por tipo y mes**")
    st.dataframe(pt, width="stretch")
    if not pt.empty:
        st.plotly_chart(px.line(pt.reset_index().melt(id_vars="mes", var_name="Tipo", value_name="Casos"), x="mes", y="Casos",
                                color="Tipo", markers=True), width="stretch")
    st.markdown("**Por canal y mes**")
    st.dataframe(pc, width="stretch")
    ui.df_descarga(pt.reset_index(), "R2_por_tipo", "r2")
with t[2]:
    if u["rol"] == "abogado":
        st.info("Este reporte es para supervisores y dirección.")
    else:
        r3 = RP.r3_desempeno(df, f_emp[0]["id"] if len(f_emp) == 1 else None)
        if u["rol"] not in ("admin", "auditor") and not r3.empty:
            nombres = {a["nombre"] for e in u["empresas"] for a in C.usuarios("abogado", e)}
            r3 = r3[r3["Abogado"].isin(nombres)]
        st.dataframe(r3, hide_index=True, width="stretch")
        ui.df_descarga(r3, "R3_desempeno", "r3")
with t[3]:
    r4 = RP.r4_vencimientos(df)
    if r4.empty:
        st.success("No hay casos abiertos.")
    else:
        st.dataframe(r4.groupby("Grupo").size().reset_index(name="Casos"), hide_index=True)
        st.dataframe(r4.rename(columns={"radicado": "Radicado", "empresa_codigo": "Empresa", "tipo_nombre": "Tipo",
                                        "abogado_nombre": "Abogado", "estado": "Estado", "fecha_vencimiento": "Vence",
                                        "sem_etiqueta": "Semáforo"}), hide_index=True, width="stretch")
        ui.df_descarga(r4, "R4_vencimientos", "r4")
with t[4]:
    r5 = RP.r5_cuellos(sids)
    st.dataframe(r5, hide_index=True, width="stretch")
    if not r5.empty:
        st.plotly_chart(px.bar(r5, x="Horas promedio", y="Estado", orientation="h"), width="stretch")
    ui.df_descarga(r5, "R5_cuellos", "r5")
with t[5]:
    r6 = RP.r6_temas(df)
    st.dataframe(r6, hide_index=True, width="stretch")
    ui.df_descarga(r6, "R6_temas", "r6")
with t[6]:
    r7 = RP.r7_satisfaccion(sids)
    if r7.empty:
        st.info("Aún no hay encuestas respondidas.")
    else:
        st.metric("Puntaje promedio (1 a 5)", round(float(r7["puntaje"].mean()), 2), help=f"{len(r7)} encuestas")
        st.bar_chart(r7["puntaje"].value_counts().sort_index())
with t[7]:
    st.markdown("**Resumen del periodo** (para la junta o entes de control). Descargue el libro de Excel con todas las hojas.")
    r1 = RP.r1_tablero(df)
    pt, pc = RP.r2_tipo_canal(df)
    hojas = {"R1 Tablero": r1, "R2 Tipo": pt.reset_index(), "R2 Canal": pc.reset_index(), "R4 Vencimientos": RP.r4_vencimientos(df),
             "R5 Cuellos": RP.r5_cuellos(sids), "R6 Temas": RP.r6_temas(df), "Listado": RP.listado(filas)}
    st.download_button("⬇️ Informe periódico (Excel, varias hojas)", RP.a_excel(hojas),
                       f"R9_informe_{desde:%Y%m%d}_{hasta:%Y%m%d}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
    st.dataframe(r1, hide_index=True, width="stretch")
