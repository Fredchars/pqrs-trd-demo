"""Utilidades de interfaz compartidas por todas las páginas."""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from core import config, flujo
from core import consultas as C
from core.servicios import ErrorNegocio

PAGINAS: dict = {}  # nombre -> st.Page (lo llena Inicio.py)

COLORES = {"verde": ("#DCFCE7", "#14532D"), "amarillo": ("#FEF9C3", "#713F12"), "rojo": ("#FEE2E2", "#7F1D1D"),
           "negro": ("#1F2937", "#FFFFFF"), "pausa": ("#E0E7FF", "#312E81"), "cerrado": ("#F1F5F9", "#334155"),
           "pendiente": ("#F1F5F9", "#334155")}

CSS = """
<style>
.sem { display:inline-block; padding:.15rem .55rem; border-radius:999px; font-weight:600; font-size:.92rem; border:1px solid rgba(0,0,0,.12); }
.logo-emp { display:inline-flex; align-items:center; justify-content:center; width:44px; height:44px; border-radius:10px;
            color:#fff; font-weight:800; font-size:1.05rem; margin-right:.6rem; vertical-align:middle; }
.emp-head { display:flex; align-items:center; margin:.2rem 0 .8rem 0; background:#fff; border:1px solid #E2E8F0; border-radius:14px;
            padding:.6rem .9rem; box-shadow:0 2px 10px rgba(18,53,91,.08); }
.emp-head .nombre { font-size:1.25rem; font-weight:700; color:#12355B; }
.caja { border:1px solid #CBD5E1; border-radius:.6rem; padding:.8rem 1rem; background:#F8FAFC; }
.ayuda { color:#334155; font-size:.95rem; }
.marca { display:flex; align-items:center; gap:.6rem; padding:.2rem 0 .5rem 0; }
.marca .logo { font-size:1.9rem; background:linear-gradient(135deg,#0EA5A4,#1E5AA8); border-radius:12px; width:46px; height:46px; display:flex; align-items:center; justify-content:center; }
.marca .t { font-weight:800; font-size:1.15rem; line-height:1.1; } .marca .s { font-size:.78rem; opacity:.8; }
.usuario-card { background:rgba(255,255,255,.1); border:1px solid rgba(255,255,255,.2); border-radius:12px; padding:.55rem .7rem; margin-bottom:.5rem; }
.usuario-card .av { display:inline-flex; width:34px; height:34px; border-radius:50%; background:#0EA5A4; color:#fff; font-weight:800; align-items:center; justify-content:center; margin-right:.5rem; }
</style>
"""


def estilos():
    import tema
    tema.estilos()
    st.markdown(CSS, unsafe_allow_html=True)


def pie():
    """Pie «Powered by ATm Consulting»: se dibuja en TODAS las pantallas (también en modo formulario)."""
    import tema
    tema.pie()


CSS_FORMULARIO = """
<style>
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="collapsedControl"],
[data-testid="stSidebarNav"], header[data-testid="stHeader"], [data-testid="stToolbar"],
[data-testid="stDecoration"], [data-testid="stStatusWidget"], footer { display: none !important; }
[data-testid="stMainBlockContainer"], .block-container { padding-top: .8rem !important; padding-bottom: 3.5rem !important;
  max-width: 900px; }
.beta-banner { font-size: .85rem; padding: .3rem .7rem; }
</style>
"""


def es_modo_formulario() -> bool:
    return str(st.query_params.get("modo", "")).lower() == "formulario"


def modo_formulario():
    """Oculta menú, barra lateral y cabecera de Streamlit (formulario insertado en otra web)."""
    st.markdown(CSS_FORMULARIO, unsafe_allow_html=True)


def aviso_beta():
    st.markdown("<div class='beta-banner' role='alert'>⚠️ PROTOTIPO BETA · SOLO DATOS FICTICIOS "
                "<small>— No registre información real de personas. Plazos y textos legales por validar con jurídica.</small></div>",
                unsafe_allow_html=True)


def usuario() -> dict | None:
    from core import sesion
    u = st.session_state.get("usuario")
    if not u and not st.session_state.get("sesion_cerrada"):
        uid = sesion.validar(st.query_params.get(sesion.PARAM))  # recarga de página: se restaura la sesión
        if uid:
            fresco = C.usuario(uid)
            if fresco and fresco.get("activo", True):
                st.session_state["usuario"] = u = {"id": fresco["id"], "email": fresco["email"]}
    if not u:
        return None
    fresco = C.usuario(u["id"])
    if not fresco or not fresco.get("activo", True):
        return None
    return {**fresco, "origen": "app"}


def mantener_sesion(u: dict | None):
    """Deja el token firmado en la URL (?s=) para que una recarga no cierre la sesión."""
    from core import sesion
    if not u:
        return
    actual = st.query_params.get(sesion.PARAM)
    if sesion.validar(actual) != u["id"]:
        st.session_state["token_sesion"] = sesion.emitir(u["id"])
        st.query_params[sesion.PARAM] = st.session_state["token_sesion"]
    elif not actual:
        st.query_params[sesion.PARAM] = st.session_state.get("token_sesion") or sesion.emitir(u["id"])


def requiere(*roles: str) -> dict:
    u = usuario()
    if not u:
        st.info("Esta pantalla es para usuarios internos. Ingrese desde **Ingresar**.")
        st.stop()
    if roles and u["rol"] not in roles:
        st.warning(f"Su rol ({C.ROLES.get(u['rol'], u['rol'])}) no tiene acceso a esta pantalla.")
        st.stop()
    return u


def semaforo_html(s: dict) -> str:
    bg, fg = COLORES.get(s.get("sem_nivel", "pendiente"), COLORES["pendiente"])
    return f"<span class='sem' style='background:{bg};color:{fg}'>{html.escape(s.get('sem_etiqueta', ''))}</span>"


def logo_html(emp: dict, tam: int = 44) -> str:
    color = emp.get("color") or "#1F3A5F"
    if emp.get("logo_url"):
        return f"<img src='{html.escape(emp['logo_url'])}' alt='Logo {html.escape(emp['nombre'])}' width='{tam}' height='{tam}'/>"
    return (f"<span class='logo-emp' role='img' aria-label='Logo {html.escape(emp['nombre'])}' "
            f"style='background:{color};width:{tam}px;height:{tam}px'>{html.escape(emp['codigo'][-2:])}</span>")


def encabezado_empresa(emp: dict, subtitulo: str = ""):
    st.markdown(f"<div class='emp-head'>{logo_html(emp)}<div><div class='nombre'>{html.escape(emp['nombre'])}</div>"
                f"<div class='ayuda'>{html.escape(subtitulo)}</div></div></div>", unsafe_allow_html=True)


def ayuda(texto: str):
    with st.expander("❓ Ayuda de esta pantalla"):
        st.markdown(texto)


def error(e: Exception):
    if isinstance(e, ErrorNegocio):
        st.error(f"⚠️ {e}")
    else:
        st.error(f"Ocurrió un error inesperado: {e}. Intente de nuevo; si persiste, avise al administrador.")


def abrir_caso(sid: int):
    st.session_state["caso_id"] = sid
    st.switch_page(PAGINAS["detalle"])


def tabla_casos(filas: list[dict], key: str, extra: dict | None = None, alto: int | None = None, abrir: bool = True):
    """Tabla ordenada por vencimiento con semáforo (ícono + texto). Seleccione una fila y pulse «Abrir caso»."""
    from core.reportes import listado
    if not filas:
        import tema
        tema.vacio("📭", "No hay casos para mostrar", "Cambie los filtros o vuelva más tarde: cuando haya casos aparecerán aquí.")
        return None
    df = listado(filas, extra)
    sel = st.dataframe(df, hide_index=True, width="stretch", height=alto or min(38 * (len(df) + 1) + 3, 520),
                       on_select="rerun" if abrir else "ignore", selection_mode="single-row", key=key,
                       column_config={"Asunto": st.column_config.TextColumn(width="large")})
    if abrir:
        filas_sel = sel.selection.rows if sel and hasattr(sel, "selection") else []
        c1, c2 = st.columns([1, 3])
        if c1.button("📂 Abrir caso", key=f"{key}-abrir", disabled=not filas_sel, type="primary"):
            abrir_caso(filas[filas_sel[0]]["id"])
        c2.caption("Seleccione una fila (casilla de la izquierda) y pulse «Abrir caso».")
    return df


def campana(u: dict):
    nuevas = C.alertas_usuario(u["id"], solo_no_leidas=True, limite=30)
    with st.sidebar.popover(f"🔔 Alertas ({len(nuevas)})", width="stretch"):
        if not nuevas:
            st.caption("No tiene alertas nuevas.")
        for a in nuevas[:15]:
            st.markdown(f"**{html.escape(a['tipo'].replace('_', ' '))}** · {html.escape(a['mensaje'] or '')}")
            c1, c2 = st.columns(2)
            if a.get("solicitud_id") and c1.button("Abrir", key=f"al-ab-{a['id']}"):
                from core import servicios
                servicios.marcar_alerta_leida(a["id"], u)
                abrir_caso(a["solicitud_id"])
            if c2.button("Leída", key=f"al-le-{a['id']}"):
                from core import servicios
                servicios.marcar_alerta_leida(a["id"], u)
                st.rerun()
        if nuevas and st.button("Marcar todas como leídas", key="al-todas"):
            from core import servicios
            servicios.marcar_todas_leidas(u)
            st.rerun()


def info_motor():
    from core.repositorio import obtener_repo
    r = obtener_repo()
    motor = "Supabase (PostgreSQL)" if r.es_pg else "Demo local (SQLite)"
    from core import correo
    if correo.modo() == "real":
        st.sidebar.caption(f"Datos: {motor} · Correo: REAL ({config.correo_servidor()['smtp_host']})")
    else:
        st.sidebar.caption(f"Datos: {motor}")
        st.sidebar.warning("✉️ Correo SIMULADO: no se envía nada real; ver «Buzón simulado».")


def df_descarga(df: pd.DataFrame, nombre: str, key: str):
    from core.reportes import a_csv, a_excel
    c1, c2 = st.columns(2)
    c1.download_button("⬇️ Excel", a_excel({nombre: df}), f"{nombre}.xlsx", key=f"{key}-x",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    c2.download_button("⬇️ CSV", a_csv(df), f"{nombre}.csv", key=f"{key}-c", mime="text/csv")


def estado_es(s: dict, *estados: str) -> bool:
    return s["estado"] in estados


def explicar(estado: str) -> str:
    return flujo.explicar(estado)


def es_demo() -> bool:
    return not config.supabase_auth_activo()
