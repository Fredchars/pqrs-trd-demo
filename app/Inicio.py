"""PQRS del Consorcio · Prototipo beta. Punto de entrada: menú según el rol (st.navigation)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
for p in (str(RAIZ), str(RAIZ / "app")):
    if p not in sys.path:
        sys.path.insert(0, p)

import streamlit as st  # noqa: E402

st.set_page_config(page_title="PQRS Consorcio · Beta", page_icon="📨", layout="wide")

# Secretos de Streamlit -> variables de entorno (core/ solo lee el entorno). Nunca se guardan en el repo.
CLAVES = ["DATABASE_URL", "SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_SERVICE_KEY",
          "MAIL_USER", "MAIL_APP_PASSWORD", "MAIL_MODO", "MAIL_SMTP_HOST", "MAIL_SMTP_PORT",
          "MAIL_SMTP_STARTTLS", "MAIL_IMAP_HOST", "MAIL_IMAP_PORT", "MAIL_FROM", "APP_URL", "PQRS_BACKEND", "PQRS_LOGIN_DEMO", "PQRS_DEMO_CLAVE", "PQRS_SESION_SECRETO", "PQRS_AHORA", "PQRS_DATA_DIR"]
try:
    if os.environ.get("PQRS_IGNORAR_SECRETS", "").lower() in ("si", "sí", "1", "true"):
        for k in CLAVES:  # Streamlit también exporta los secretos al entorno: se retiran para forzar la demo
            if k not in ("PQRS_AHORA", "PQRS_DATA_DIR", "PQRS_BACKEND"):
                os.environ.pop(k, None)
        # URL de los enlaces y del QR en la demo local: PQRS_DEMO_URL o el puerto con el que se lanzó Streamlit.
        os.environ["APP_URL"] = os.environ.get("PQRS_DEMO_URL") or f"http://localhost:{st.get_option('server.port')}"
        raise RuntimeError("secretos ignorados")  # útil para correr la demo local con un secrets.toml presente
    for k in CLAVES:
        if k in st.secrets and not os.environ.get(k):
            os.environ[k] = str(st.secrets[k])
except Exception:  # sin secrets.toml: modo demo
    pass

import ui  # noqa: E402
from core import consultas as C  # noqa: E402
from core.repositorio import obtener_repo  # noqa: E402


@st.cache_resource(show_spinner="Preparando la base de datos de demostración…")
def _repo():
    return obtener_repo()


try:
    _repo()
except Exception as e:  # pragma: no cover - errores de conexión
    st.error(f"No se pudo conectar con la base de datos: {e}. Revise los secretos (DATABASE_URL) o quite la "
             "configuración para usar el modo demo.")
    st.stop()

ui.estilos()
D = "paginas"
P = {
    "radicar": st.Page(f"{D}/radicar.py", title="Radicar PQRS", icon="📝", url_path="radicar"),
    "consultar": st.Page(f"{D}/consultar_estado.py", title="Consultar estado", icon="🔎", url_path="consultar_estado"),
    "ingresar": st.Page(f"{D}/ingresar.py", title="Ingresar (usuarios internos)", icon="🔐", url_path="ingresar"),
    "bandeja": st.Page(f"{D}/mi_bandeja.py", title="Mi bandeja", icon="📥", url_path="mi_bandeja"),
    "detalle": st.Page(f"{D}/detalle_caso.py", title="Detalle del caso", icon="📂", url_path="detalle_caso"),
    "aprobaciones": st.Page(f"{D}/aprobaciones.py", title="Aprobaciones", icon="✅", url_path="aprobaciones"),
    "supervision": st.Page(f"{D}/supervision.py", title="Supervisión", icon="🧭", url_path="supervision"),
    "busqueda": st.Page(f"{D}/busqueda.py", title="Búsqueda", icon="🔍", url_path="busqueda"),
    "reportes": st.Page(f"{D}/reportes.py", title="Reportes", icon="📊", url_path="reportes"),
    "administracion": st.Page(f"{D}/administracion.py", title="Administración", icon="⚙️", url_path="administracion"),
    "buzon": st.Page(f"{D}/buzon_simulado.py", title="Buzón de correo", icon="✉️", url_path="buzon"),
    "bitacora": st.Page(f"{D}/bitacora.py", title="Bitácora", icon="📜", url_path="bitacora"),
    "inicio": st.Page(f"{D}/inicio.py", title="Inicio", icon="🏠", url_path="inicio"),
    "trd": st.Page(f"{D}/trd_series.py", title="TRD (series)", icon="🗂️", url_path="trd"),
    "expedientes": st.Page(f"{D}/expedientes.py", title="Expedientes", icon="📁", url_path="expedientes"),
    "cajas": st.Page(f"{D}/cajas_rotulos.py", title="Cajas y rótulos QR", icon="📦", url_path="cajas"),
    "prestamos": st.Page(f"{D}/prestamos.py", title="Préstamos", icon="🔄", url_path="prestamos"),
    "vencimientos": st.Page(f"{D}/vencimientos.py", title="Vencimientos y disposición", icon="⏰", url_path="vencimientos"),
    "reportes_archivo": st.Page(f"{D}/reportes_archivo.py", title="Reportes de archivo", icon="📊", url_path="reportes_archivo"),
    "exportacion": st.Page(f"{D}/exportacion.py", title="Exportar empresa", icon="📦", url_path="exportacion"),
}
ui.PAGINAS.update(P)

ARCHIVO = ["trd", "expedientes", "cajas", "prestamos", "vencimientos", "reportes_archivo"]
# Menú agrupado por tareas: título del grupo -> páginas (la primera del primer grupo es el inicio del rol)
MENU = {
    "abogado": {"🏠 Mi trabajo": ["inicio", "bandeja", "detalle"], "🔎 Consultas": ["busqueda", "reportes"],
                "🗂️ Archivo (consulta)": ["trd", "expedientes", "cajas", "prestamos"]},
    "radicador": {"🏠 Mi trabajo": ["inicio", "bandeja", "detalle", "buzon"], "🔎 Consultas": ["busqueda"]},
    "supervisor": {"🏠 Mi trabajo": ["inicio", "supervision", "bandeja", "aprobaciones", "detalle"],
                   "🔎 Consultas y reportes": ["busqueda", "reportes", "buzon"], "🗂️ TRD y archivo": ARCHIVO},
    "director": {"🏠 Mi trabajo": ["inicio", "aprobaciones", "supervision", "detalle"], "🔎 Consultas y reportes": ["busqueda", "reportes"],
                 "🗂️ TRD y archivo": ARCHIVO},
    "archivista": {"🗂️ Archivo": ["inicio", "expedientes", "cajas", "prestamos", "vencimientos"],
                   "📚 TRD y reportes": ["trd", "reportes_archivo"], "🔎 Consultas": ["busqueda", "detalle"]},
    "admin": {"⚙️ Administración": ["inicio", "administracion", "bitacora", "exportacion"],
              "🏠 Operación": ["supervision", "buzon", "detalle", "busqueda", "reportes"], "🗂️ TRD y archivo": ARCHIVO},
    "auditor": {"🔎 Auditoría": ["inicio", "bitacora", "exportacion"], "📊 Consultas": ["reportes", "busqueda", "detalle"],
                "🗂️ TRD y archivo (lectura)": ARCHIVO},
    "integracion": {"🔎 Consultas": ["busqueda", "detalle"]},
}

u = ui.usuario()
# Modo formulario (para insertar en la web de una empresa con <iframe>): ?modo=formulario&empresa=EMP01
# Muestra SOLO el formulario público, sin menú ni barra lateral. (Streamlit Cloud no entrega ?embed=true a la app.)
modo_formulario = str(st.query_params.get("modo", "")).lower() == "formulario"
embed = modo_formulario or str(st.query_params.get("embed", "")).lower() == "true"
publicas = [P["radicar"], P["consultar"]]
qr_codigo = str(st.query_params.get("codigo", "")).strip()
if modo_formulario:
    ui.modo_formulario()
    nav = st.navigation([P["radicar"]], position="hidden")
elif u:
    grupos = {}
    for titulo, nombres in MENU.get(u["rol"], {}).items():
        lista = []
        for nombre in nombres:
            pg = P[nombre]
            if nombre == "detalle":
                pg = st.Page(f"{D}/detalle_caso.py", title="Detalle del caso", icon="📂", url_path="detalle_caso",
                             visibility="visible" if st.session_state.get("caso_id") else "hidden")
                ui.PAGINAS["detalle"] = pg
            elif nombre == "inicio":
                pg = st.Page(f"{D}/inicio.py", title="Inicio", icon="🏠", url_path="inicio", default=True)
                ui.PAGINAS["inicio"] = pg
            lista.append(pg)
        grupos[titulo] = lista
    ui.PAGINAS["cajas_ok"] = any(pg.url_path == "cajas" for lista in grupos.values() for pg in lista)
    primero = next(iter(grupos.values()))[0]
    ui.PAGINAS["inicio_rol"] = primero
    ingreso_oculto = st.Page(f"{D}/ingresar.py", title="Ingresar", icon="🔐", url_path="ingresar", visibility="hidden")
    grupos["📝 Atención al ciudadano"] = publicas + [ingreso_oculto]
    nav = st.navigation(grupos, position="hidden" if embed else "sidebar", expanded=True)
else:
    ingresar = P["ingresar"]
    # El QR de un rótulo apunta a /cajas?codigo=...: sin sesión la página «cajas» existe (oculta), recuerda el destino y
    # lleva al ingreso; así no aparece «Page not found» y, al ingresar, se abre la caja.
    if qr_codigo:
        st.session_state["destino_qr"] = qr_codigo
    publicas = publicas + [st.Page(f"{D}/cajas_rotulos.py", title="Cajas y rótulos QR", icon="📦", url_path="cajas", visibility="hidden")]
    nav = st.navigation({"Atención al ciudadano": publicas, "Usuarios internos": [ingresar]},
                        position="hidden" if embed else "sidebar")

if not embed:
    with st.sidebar:
        st.markdown("<div class='marca'><div class='logo'>📨</div><div><div class='t'>PQRS Consorcio</div>"
                    "<div class='s'>Prototipo beta · datos ficticios</div></div></div>", unsafe_allow_html=True)
        if u:
            import html as _h
            emps = [C.empresa(e)["codigo"] for e in u.get("empresas", []) if C.empresa(e)]
            ini = "".join(w[0] for w in (u["nombre"] or "?").split()[:2]).upper()
            st.markdown(f"<div class='usuario-card'><span class='av'>{_h.escape(ini)}</span><b>{_h.escape(u['nombre'])}</b><br>"
                        f"<span style='font-size:.85rem;opacity:.9'>{_h.escape(C.ROLES.get(u['rol'], u['rol']))} · "
                        f"{_h.escape(', '.join(emps) if len(emps) <= 3 else str(len(emps)) + ' empresas')}</span></div>", unsafe_allow_html=True)
            ui.campana(u)
            if st.button("Cerrar sesión", width="stretch"):
                for k in list(st.session_state.keys()):
                    del st.session_state[k]
                st.query_params.pop("s", None)
                st.session_state["sesion_cerrada"] = True
                st.rerun()
        ui.info_motor()

if u and not modo_formulario:
    ui.mantener_sesion(u)
ui.pie()  # «Powered by ATm Consulting» en todas las pantallas (se dibuja antes de la página: st.stop() corta el resto)
nav.run()
