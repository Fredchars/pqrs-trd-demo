"""Respuestas pendientes de aprobación (supervisor: nivel 1; director: nivel 2)."""
import streamlit as st

import ui
from core import consultas as C
from core import servicios as S

ui.aviso_beta()
u = ui.requiere("supervisor", "director", "admin")
st.title("✅ Aprobaciones")
en_rev = C.listar_solicitudes(u, {"estado": ["EN_REVISION"]})
mias, otras = [], []
for s in en_rev:
    ok, n, nota = S.puede_aprobar(s, u)
    s["nivel_pendiente"] = n
    s["nota"] = nota
    (mias if ok else otras).append(s)
st.metric("Pendientes de su aprobación", len(mias))
st.caption("Abra el caso para ver el texto, los cambios entre versiones y los comentarios anteriores en la misma pantalla.")
ui.tabla_casos(mias, "apr-mias", {"nivel_pendiente": "Nivel"})
with st.expander(f"Otras respuestas en revisión de sus empresas ({len(otras)})"):
    ui.tabla_casos(otras, "apr-otras", {"nivel_pendiente": "Nivel", "nota": "Quién aprueba"})
aprobadas = C.listar_solicitudes(u, {"estado": ["APROBADA"]})
with st.expander(f"Aprobadas pendientes de envío ({len(aprobadas)})"):
    ui.tabla_casos(aprobadas, "apr-env")
ui.ayuda("Esquemas: **A** sin aprobación (sugerencias) · **B** un nivel: supervisor · **C** dos niveles: supervisor y "
         "director (temas sensibles). Si el aprobador titular está ausente, su **suplente** puede aprobar. Si el caso vence "
         "hoy, el supervisor puede **aprobar y enviar** en un solo paso.")
