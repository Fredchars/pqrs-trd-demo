"""Bandeja según el rol: abogado (sus casos), supervisor (su empresa) y radicador (recibidas, duplicados, ventanilla)."""
import streamlit as st

import formularios
import ui
from core import consultas as C
from core import servicios as S

ui.aviso_beta()
u = ui.requiere("abogado", "supervisor", "radicador")
st.title("📥 Mi bandeja")

if u["rol"] == "radicador":
    t1, t2, t3 = st.tabs(["Recibidas por revisar", "Posibles duplicados", "Registrar PQRS presencial o telefónica"])
    recibidas = C.listar_solicitudes(u, {"estado": ["RECIBIDA"]})
    with t1:
        st.caption("Casos de su empresa en estado RECIBIDA (sin asignar o pendientes de revisión).")
        ui.tabla_casos(recibidas, "rad-rec")
    with t2:
        dups = [s for s in recibidas if s.get("revisar_duplicado")]
        if not dups:
            st.success("No hay posibles duplicados por revisar.")
        for s in dups:
            orig = C.obtener_solicitud(s["posible_duplicado_de"], sin_alcance=True)
            with st.container(border=True):
                st.markdown(f"**{s['radicado']}** · {s['asunto']}  \nSe parece a **{orig['radicado']}** · {orig['asunto']} "
                            f"({orig.get('solicitante_nombre')})")
                c1, c2, c3 = st.columns(3)
                motivo = st.text_input("Motivo (obligatorio para anular)", key=f"dm-{s['id']}")
                try:
                    if c1.button("🔗 Vincular (misma respuesta)", key=f"dv-{s['id']}"):
                        S.resolver_duplicado(s["id"], "vincular", u)
                        st.rerun()
                    if c2.button("✔ No es duplicado", key=f"dn-{s['id']}"):
                        S.resolver_duplicado(s["id"], "no_duplicado", u)
                        st.rerun()
                    if c3.button("🗑 Anular", key=f"da-{s['id']}"):
                        S.resolver_duplicado(s["id"], "anular", u, motivo)
                        st.rerun()
                except Exception as e:
                    ui.error(e)
    with t3:
        formularios.formulario_radicacion(usuario=u, clave="vent")
    st.stop()

filtro = {"abiertos": True}
if u["rol"] == "abogado":
    filtro["abogado_id"] = u["id"]
casos = C.listar_solicitudes(u, filtro)
borradores = {r["solicitud_id"]: r for r in C.R().q(
    "select solicitud_id, version, origen from respuestas where estado = 'borrador' and origen = 'mcp'")}
devueltas = {r["solicitud_id"] for r in C.R().q("select solicitud_id from respuestas where estado = 'devuelta'")}
for s in casos:
    marcas = []
    if s["id"] in borradores:
        marcas.append("🤖 borrador del asistente")
    if s["id"] in devueltas and s["estado"] == "EN_TRAMITE":
        marcas.append("↩️ devuelta")
    if s.get("prorrogada"):
        marcas.append("⏩ prorrogada")
    if s.get("respuesta_parcial"):
        marcas.append("½ parcial")
    s["marcas"] = " · ".join(marcas)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Casos abiertos", len(casos))
c2.metric("🔴 Rojos / vencen hoy", sum(1 for s in casos if s["sem_nivel"] == "rojo"))
c3.metric("⛔ Vencidos", sum(1 for s in casos if s["sem_nivel"] == "negro"))
c4.metric("🤖 Borradores del asistente", sum(1 for s in casos if s["id"] in borradores))

vista = st.segmented_control("Ver", ["Todos", "Por vencer (rojos y vencidos)", "Devueltos", "Borradores del asistente",
                                     "Esperando al ciudadano"], default="Todos", key="vista-bandeja")
if vista == "Por vencer (rojos y vencidos)":
    casos = [s for s in casos if s["sem_nivel"] in ("rojo", "negro")]
elif vista == "Devueltos":
    casos = [s for s in casos if "devuelta" in s["marcas"]]
elif vista == "Borradores del asistente":
    casos = [s for s in casos if s["id"] in borradores]
elif vista == "Esperando al ciudadano":
    casos = [s for s in casos if s["estado"] == "PENDIENTE_INFO"]
st.caption("Ordenado por fecha de vencimiento: lo más urgente arriba. El semáforo usa color, ícono y texto.")
ui.tabla_casos(casos, "bandeja", {"marcas": "Marcas"})
ui.ayuda("""
**Cómo gestionar un caso (3 clics):** 1) seleccione la fila, 2) pulse **Abrir caso**, 3) en la pestaña *Respuesta*
elija una plantilla y pulse **Enviar a revisión**.  
🟢 más del 50 % del plazo disponible · 🟡 entre 50 % y 80 % consumido · 🔴 más del 80 % o vence hoy · ⛔ vencido ·
⏸️ plazo suspendido mientras el ciudadano aporta información.
""")
