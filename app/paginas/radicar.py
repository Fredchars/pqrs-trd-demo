"""Formulario público de PQRS. Para insertarlo en otra web: ?modo=formulario&empresa=EMP01 (solo el formulario)."""
import streamlit as st

import formularios
import tema
import ui
from core import consultas as C

from core.config import app_url

formulario = ui.es_modo_formulario()
ui.aviso_beta()
cod = str(st.query_params.get("empresa", "")).upper()
emp = C.empresa_por_codigo(cod) if cod else None
if emp:
    ui.encabezado_empresa(emp, "Peticiones, quejas, reclamos y sugerencias (PQRS)")
elif formulario:
    st.markdown("#### 📝 Radique su petición, queja, reclamo o sugerencia")
else:
    tema.hero("Radique su petición, queja, reclamo o sugerencia", "Es rápido, gratuito y puede seguir su caso en línea.", "📝",
              ["Sin registro previo", "Acuse por correo", "Consulta con su código"])
    c1, c2, c3 = st.columns(3)
    for c, n, t, d in ((c1, "1", "Cuéntenos", "Complete el formulario con sus datos y lo que ocurrió."),
                       (c2, "2", "Reciba su radicado", "Verá un número de radicado y un código de consulta."),
                       (c3, "3", "Siga su caso", "Consulte el estado en «Consultar estado» cuando quiera.")):
        c.markdown(f"<div class='paso'><span class='n'>{n}</span><b>{t}</b><br><span class='sub'>{d}</span></div>", unsafe_allow_html=True)
    st.write("")
st.markdown("Complete el formulario. Al enviarlo verá su **número de radicado** y un **código de consulta**, "
            "y le llegará un acuse por correo.")
if formulario:
    st.caption(f"¿Ya radicó? Consulte el estado en [{app_url().replace('https://', '')}/consultar_estado]"
               f"({app_url()}/consultar_estado).")
formularios.formulario_radicacion(empresa_fija=emp, clave="pub")
ui.ayuda("""
- **Petición**: pedir algo. **Queja**: inconformidad con la atención. **Reclamo**: corregir un problema o cobro.
- Los plazos se cuentan en **días hábiles** (sin sábados, domingos ni festivos de Colombia).
- Lo que llegue después de la hora de corte (5:00 p. m.) o en día no hábil se radica el siguiente día hábil.
""")
if not formulario:
    with st.expander("🌐 Insertar este formulario en la página web de una empresa"):
        st.markdown("Copie este código en su sitio (por ejemplo, un bloque «HTML personalizado» en Hostinger). "
                    "Cambie `EMP01` por el código de la empresa. Solo se verá el formulario, sin el menú.")
        st.code(f'<iframe src="{app_url()}/~/+/?modo=formulario&empresa={(emp or {}).get("codigo", "EMP01")}&embed=true"\n'
                '        width="100%" height="1100" style="border:0" title="Formulario PQRS"></iframe>', language="html")
