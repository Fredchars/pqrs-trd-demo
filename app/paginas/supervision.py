"""Visión del supervisor (RU-15): carga por abogado, por vencer, vencidos, cola sin asignar y ausencias."""
from datetime import timedelta

import pandas as pd
import streamlit as st

import ui
from core import consultas as C
from core import servicios as S
from core.reloj import hoy

ui.aviso_beta()
u = ui.requiere("supervisor", "director", "admin")
st.title("🧭 Supervisión del equipo")
emps = [C.empresa(e) for e in u["empresas"]] if u["rol"] != "admin" else C.empresas()
emp = st.selectbox("Empresa", emps, format_func=lambda e: f"{e['codigo']} · {e['nombre']}") if len(emps) > 1 else emps[0]
casos = C.listar_solicitudes(u, {"empresa_id": emp["id"], "abiertos": True})
carga = pd.DataFrame(C.carga_equipo(emp["id"]))
c1, c2, c3, c4 = st.columns(4)
c1.metric("Abiertos", len(casos))
c2.metric("🔴 Por vencer (≤2 días)", sum(1 for s in casos if s.get("dias_restantes") is not None and 0 <= s["dias_restantes"] <= 2
                                       and s["estado"] != "PENDIENTE_INFO"))
c3.metric("⛔ Vencidos", sum(1 for s in casos if s["sem_nivel"] == "negro"))
cola = [s for s in casos if not s.get("abogado_id")]
c4.metric("📭 Sin asignar (cola)", len(cola))

st.subheader("Carga por abogado")
if not carga.empty:
    vista = carga.rename(columns={"abogado": "Abogado", "casos_abiertos": "Casos abiertos", "carga_ponderada": "Carga ponderada",
                                  "capacidad_max": "Capacidad", "especialidades": "Especialidades"})
    vista["Disponible"] = carga.apply(lambda r: "🟢 Sí" if r["disponible"] else ("🏖 Ausente" if r["ausente"] else "⛔ No"), axis=1)
    st.dataframe(vista[["Abogado", "Casos abiertos", "Carga ponderada", "Capacidad", "Disponible", "Especialidades"]],
                 hide_index=True, width="stretch")
    st.bar_chart(vista.set_index("Abogado")["Carga ponderada"], horizontal=True, height=200)
    st.caption(f"Estrategia de reparto de {emp['codigo']}: **{emp['estrategia_reparto']}** "
               "(E = especialidad + menor carga ponderada; si no hay candidatos, cola del supervisor).")

t1, t2, t3, t4 = st.tabs(["Por vencer y vencidos", "Cola sin asignar", "Todos los abiertos", "Ausencias"])
with t1:
    ui.tabla_casos([s for s in casos if s["sem_nivel"] in ("rojo", "negro")], "sup-venc")
with t2:
    if cola:
        ui.tabla_casos(cola, "sup-cola")
        sel = st.selectbox("Asignar manualmente", cola, format_func=lambda s: f"{s['radicado']} · {s['asunto']}", key="sup-cola-sel")
        abog = C.usuarios("abogado", emp["id"])
        ab = st.selectbox("A", abog, format_func=lambda a: a["nombre"], key="sup-cola-ab")
        mot = st.text_input("Motivo", value="Asignación manual desde la cola", key="sup-cola-mot")
        if st.button("Asignar", key="sup-cola-btn"):
            try:
                S.reasignar(sel["id"], ab["id"], mot, u)
                st.rerun()
            except Exception as e:
                ui.error(e)
    else:
        st.success("No hay casos en la cola del supervisor.")
with t3:
    ui.tabla_casos(casos, "sup-todos")
with t4:
    abog = C.usuarios("abogado", emp["id"])
    a = st.selectbox("Abogado", abog, format_func=lambda x: f"{x['nombre']}" + (f" · ausente {x['ausente_desde']} a {x['ausente_hasta']}" if x["ausente_desde"] else ""))
    c1, c2 = st.columns(2)
    d = c1.date_input("Desde", hoy(), format="DD/MM/YYYY")
    h = c2.date_input("Hasta", hoy() + timedelta(days=5), format="DD/MM/YYYY")
    modo = st.radio("Sus casos abiertos", ["reasignar", "conservar"], horizontal=True,
                    format_func=lambda m: "Reasignarlos automáticamente (estrategia A)" if m == "reasignar"
                    else "Conservarlos (solo se mueven los que vencen durante la ausencia)")
    b1, b2 = st.columns(2)
    if b1.button("Registrar ausencia", type="primary"):
        try:
            if u["rol"] == "director":
                raise S.ErrorNegocio("Las ausencias las registra el supervisor.")
            r = S.marcar_ausencia(a["id"], d, h, modo == "reasignar", u)
            st.success(f"Ausencia registrada. Reasignados: {len(r['reasignados'])} · Conservados: {len(r['conservados'])}")
            if r["reasignados"]:
                st.dataframe(pd.DataFrame(r["reasignados"], columns=["Radicado", "Nuevo responsable"]), hide_index=True)
        except Exception as e:
            ui.error(e)
    if a["ausente_desde"] and b2.button("Terminar ausencia"):
        try:
            S.quitar_ausencia(a["id"], u)
            st.rerun()
        except Exception as e:
            ui.error(e)
