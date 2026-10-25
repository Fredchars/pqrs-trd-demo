"""Inicio de sesión: Supabase Auth (correo y contraseña) o selector de usuarios ficticios (modo demo)."""
import streamlit as st

import ui
from core import catalogo_demo, config
from core import consultas as C
from core.repositorio import obtener_repo

ui.aviso_beta()
if ui.usuario():
    st.switch_page(ui.PAGINAS.get("inicio_rol") or ui.PAGINAS["radicar"])

import tema

tema.hero("Ingreso de usuarios internos", "Abogados, supervisores, archivistas, radicadores y administradores.", "🔐")


def _entrar(u: dict):
    st.session_state["usuario"] = {"id": u["id"], "email": u["email"]}
    st.session_state.pop("caso_id", None)
    st.session_state.pop("sesion_cerrada", None)
    st.rerun()


if config.supabase_auth_activo():
    st.caption("Inicio de sesión con Supabase Auth (correo y contraseña).")
    with st.form("login"):
        email = st.text_input("Correo electrónico", autocomplete="username")
        clave = st.text_input("Contraseña", type="password", autocomplete="current-password")
        ok = st.form_submit_button("Ingresar", type="primary")
    if ok:
        import httpx
        url = config.obtener("SUPABASE_URL").rstrip("/")
        llave = config.obtener("SUPABASE_PUBLISHABLE_KEY") or config.obtener("SUPABASE_ANON_KEY")
        try:
            r = httpx.post(f"{url}/auth/v1/token?grant_type=password", json={"email": email.strip(), "password": clave},
                           headers={"apikey": llave}, timeout=20)
        except Exception as e:
            st.error(f"No se pudo contactar el servicio de autenticación: {e}")
            st.stop()
        if r.status_code != 200:
            st.error("Correo o contraseña incorrectos. Revise los datos e intente de nuevo.")
            st.stop()
        info = r.json().get("user", {})
        u = C.usuario_por_email(info.get("email", ""))
        if not u or not u["activo"]:
            st.error("Su cuenta existe en Supabase Auth pero no está registrada como usuario del sistema. "
                     "Pida al administrador que la cree.")
            st.stop()
        if info.get("id") and u.get("auth_id") != info["id"]:
            obtener_repo().actualizar("usuarios", u["id"], {"auth_id": info["id"]})
            C.limpiar_cache()
        _entrar(u)
    with st.expander("Usuarios de demostración"):
        st.markdown("Todos los usuarios son **ficticios** y comparten la contraseña de demostración que aparece en el "
                    "README del repositorio. Ejemplos: `abogado1.emp01@pqrs.example.com`, `supervisor.emp01@pqrs.example.com`, "
                    "`director@pqrs.example.com`, `admin@pqrs.example.com`, `radicador.emp01@pqrs.example.com`, "
                    "`archivista.emp01@pqrs.example.com`, `auditor@pqrs.example.com`.")
else:
    permitido, motivo = config.login_demo_permitido()
    if not permitido:
        st.error("El acceso de demostración está cerrado en este despliegue. Configure Supabase Auth "
                 "(SUPABASE_URL y SUPABASE_ANON_KEY) o defina PQRS_DEMO_CLAVE en los secretos.")
        st.stop()
    if motivo == "clave" and not st.session_state.get("demo_desbloqueado"):
        import hmac
        with st.form("clave_demo"):
            cl = st.text_input("Clave de acceso a la demostración", type="password")
            if st.form_submit_button("Continuar", type="primary"):
                if hmac.compare_digest(cl.strip().encode(), (config.obtener("PQRS_DEMO_CLAVE") or "").encode()):
                    st.session_state["demo_desbloqueado"] = True
                    st.rerun()
                st.error("Clave incorrecta.")
        st.stop()
    if motivo == "local":
        st.caption("Acceso demo sin clave solo porque esta instancia corre en local (SQLite).")
    st.info("**Modo demostración:** elija un usuario ficticio para ver la aplicación con su rol. "
            "En la versión conectada a Supabase se ingresa con correo y contraseña.")
    rapidos = [("⚖️ Abogado(a) · EMP01", f"abogado1.emp01@{catalogo_demo.DOMINIO}"),
               ("🧭 Supervisor(a) · EMP01", f"supervisor.emp01@{catalogo_demo.DOMINIO}"),
               ("🗂️ Archivista · EMP01", f"archivista.emp01@{catalogo_demo.DOMINIO}"),
               ("🏛️ Director(a) del consorcio", f"director@{catalogo_demo.DOMINIO}"),
               ("📝 Radicador(a) · EMP01", f"radicador.emp01@{catalogo_demo.DOMINIO}"),
               ("⚙️ Administrador(a)", f"admin@{catalogo_demo.DOMINIO}"),
               ("🔎 Auditor(a)", f"auditor@{catalogo_demo.DOMINIO}")]
    st.subheader("Acceso rápido")
    cols = st.columns(3)
    for i, (etq, email) in enumerate(rapidos):
        u = C.usuario_por_email(email)
        if u and cols[i % 3].button(f"{etq}\n\n{u['nombre']}", key=f"rap-{i}", width="stretch"):
            _entrar(u)
    st.subheader("Otro usuario")
    c1, c2 = st.columns(2)
    emp = c1.selectbox("Empresa", [None] + C.empresas(), format_func=lambda e: "Todas / consorcio" if e is None else f"{e['codigo']} · {e['nombre']}")
    rol = c2.selectbox("Rol", list(C.ROLES), format_func=lambda r: C.ROLES[r])
    lista = C.usuarios(rol, emp["id"] if emp else None)
    if lista:
        elegido = st.selectbox("Usuario", lista, format_func=lambda u: f"{u['nombre']} · {u['email']}")
        if st.button("Ingresar como este usuario", type="primary"):
            _entrar(elegido)
    else:
        st.caption("No hay usuarios con ese rol en esa empresa.")
