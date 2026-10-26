"""Administración: empresas, usuarios, tipos y plazos, temas, plantillas, parámetros, festivos y tareas."""
import pandas as pd
import streamlit as st

import ui
from core import consultas as C
from core import servicios as S
from core.repositorio import obtener_repo

ui.aviso_beta()
u = ui.requiere("admin")
st.title("⚙️ Administración")
st.caption("Cada cambio queda en la bitácora con el valor anterior y el nuevo. Edite en la tabla y pulse «Guardar cambios».")
repo = obtener_repo()


def editor(tabla, filas, columnas, key, deshabilitadas=("id",), config=None):
    if not filas:
        st.info("Sin registros.")
        return
    df = pd.DataFrame(filas)[list(columnas)]
    for c in df.columns:
        if df[c].map(lambda v: isinstance(v, list)).any():
            df[c] = df[c].map(lambda v: ", ".join(v) if isinstance(v, list) else (v or ""))
    nuevo = st.data_editor(df, hide_index=True, width="stretch", disabled=list(deshabilitadas), key=key,
                           column_config=config or {})
    if st.button("💾 Guardar cambios", key=f"{key}-g"):
        n = 0
        try:
            for (_, a), (_, b) in zip(df.iterrows(), nuevo.iterrows()):
                cambios = {c: (None if pd.isna(b[c]) else b[c]) for c in df.columns if c not in deshabilitadas and str(a[c]) != str(b[c])}
                for c in ("especialidades", "palabras_clave"):
                    if c in cambios and isinstance(cambios[c], str):
                        cambios[c] = [x.strip() for x in cambios[c].split(",") if x.strip()]
                if cambios:
                    S.actualizar_config(tabla, a["clave"] if tabla == "parametros" else int(a["id"]), cambios, u)
                    n += 1
            st.success(f"{n} registro(s) actualizado(s).")
        except Exception as e:
            ui.error(e)


t = st.tabs(["Empresas", "Usuarios", "Tipos y plazos", "Temas", "Plantillas", "Parámetros", "Festivos", "Tareas y demo"])
with t[0]:
    editor("empresas", C.empresas(False), ["id", "codigo", "nombre", "nit", "buzon_correo", "color", "estrategia_reparto",
                                            "acepta_anonimas", "activo"], "ed-emp", ("id", "codigo"),
           {"estrategia_reparto": st.column_config.SelectboxColumn(options=["A", "B", "C", "D", "E"])})
with t[1]:
    us = C.usuarios(activos=False)
    rol = st.selectbox("Filtrar por rol", [None] + list(C.ROLES), format_func=lambda r: "Todos" if r is None else C.ROLES[r])
    us = [x for x in us if rol is None or x["rol"] == rol]
    editor("usuarios", us, ["id", "email", "nombre", "rol", "cargo", "especialidades", "capacidad_max", "disponible",
                            "ausente_desde", "ausente_hasta", "suplente_id", "activo"], "ed-us", ("id", "email"),
           {"rol": st.column_config.SelectboxColumn(options=list(C.ROLES))})
    with st.expander("Empresas de un usuario"):
        todos = C.usuarios(activos=False)
        x = st.selectbox("Usuario", todos, format_func=lambda v: f"{v['nombre']} · {v['email']}")
        st.caption("Empresas: " + ", ".join(C.empresa(e)["codigo"] for e in x["empresas"]))
        c1, c2 = st.columns(2)
        e = c1.selectbox("Empresa", C.empresas(), format_func=lambda v: v["codigo"])
        if c1.button("Agregar empresa"):
            S.crear_config("usuario_empresa", {"usuario_id": x["id"], "empresa_id": e["id"]}, u)
            st.rerun()
        if c2.button("Quitar empresa"):
            S.quitar_empresa_usuario(x["id"], e["id"], u)
            st.rerun()
    with st.expander("Crear usuario"):
        with st.form("nuevo-us"):
            c1, c2, c3 = st.columns(3)
            em = c1.text_input("Correo (ficticio)")
            no = c2.text_input("Nombre")
            ro = c3.selectbox("Rol", list(C.ROLES))
            emp = st.multiselect("Empresas", C.empresas(), format_func=lambda v: v["codigo"])
            cap = st.number_input("Tope de casos abiertos (solo abogados; 0 = no recibe casos)", min_value=0, max_value=1000,
                                  value=S.capacidad_defecto(), step=1)
            if st.form_submit_button("Crear"):
                try:
                    if not em or not no:
                        raise S.ErrorNegocio("Escriba el correo y el nombre.")
                    S.crear_config("usuarios", {"email": em.strip().lower(), "nombre": no, "rol": ro, "activo": True,
                                                "disponible": True, "capacidad_max": int(cap), "especialidades": []}, u)
                    nu = C.usuario_por_email(em.strip().lower())
                    for e in emp:
                        S.crear_config("usuario_empresa", {"usuario_id": nu["id"], "empresa_id": e["id"]}, u)
                    st.success("Usuario creado." if not repo.es_pg else
                               "Usuario creado. En modo Supabase, créele también la cuenta de acceso (scripts/setup_supabase.py).")
                except Exception as ex:
                    ui.error(ex)
with t[2]:
    st.caption("Plazos en días hábiles. «Niveles» = aprobación (0 sin aprobación, 1 supervisor, 2 supervisor y director).")
    editor("tipos_pqrs", C.tipos(False), ["id", "codigo", "nombre", "dias_habiles", "dias_prorroga_max", "peso_carga",
                                         "niveles_aprobacion", "palabras_clave", "descripcion", "activo"], "ed-tp", ("id", "codigo"))
with t[3]:
    editor("temas", C.temas(), ["id", "nombre", "especialidad_requerida", "sensible"], "ed-tm")
with t[4]:
    ps = C.plantillas()
    p = st.selectbox("Plantilla", ps, format_func=lambda v: f"{v['clave']} · {v['nombre']}")
    with st.form("pl"):
        nom = st.text_input("Nombre", p["nombre"])
        asu = st.text_input("Asunto", p.get("asunto") or "")
        cue = st.text_area("Cuerpo", p["cuerpo"], height=280,
                           help="Variables: {{radicado}}, {{nombre}}, {{fecha_radicacion}}, {{fecha_vencimiento}}, {{empresa}}, {{abogado}}, …")
        act = st.checkbox("Activa", p["activo"])
        if st.form_submit_button("Guardar plantilla"):
            try:
                S.actualizar_config("plantillas", p["id"], {"nombre": nom, "asunto": asu, "cuerpo": cue, "activo": act}, u)
                st.success("Plantilla guardada.")
            except Exception as e:
                ui.error(e)
with t[5]:
    par = [{"clave": k, "valor": str(v)} for k, v in C.parametros().items()]
    editor("parametros", par, ["clave", "valor"], "ed-par", ("clave",))
with t[6]:
    fs = repo.q("select f.id, f.fecha, f.descripcion, e.codigo as empresa from festivos_extra f "
                "left join empresas e on e.id = f.empresa_id order by f.fecha")
    st.caption("Los festivos nacionales de Colombia ya están incluidos. Aquí se agregan días no hábiles adicionales "
               "(por ejemplo, cierre por inventario).")
    st.dataframe(pd.DataFrame(fs), hide_index=True, width="stretch")
    with st.form("fest"):
        c1, c2, c3 = st.columns(3)
        fe = c1.date_input("Fecha", format="DD/MM/YYYY")
        de = c2.text_input("Descripción")
        em = c3.selectbox("Empresa", [None] + C.empresas(), format_func=lambda v: "Todas" if v is None else v["codigo"])
        if st.form_submit_button("Agregar festivo"):
            S.crear_config("festivos_extra", {"fecha": fe, "descripcion": de or "Día no hábil",
                                              "empresa_id": em["id"] if em else None}, u)
            st.rerun()
    if fs:
        b = st.selectbox("Quitar festivo", fs, format_func=lambda v: f"{v['fecha']} · {v['descripcion']}")
        if st.button("Quitar"):
            S.borrar_festivo(b["id"], u)
            st.rerun()
with t[7]:
    if repo.es_pg:
        st.markdown("**Tareas programadas** (en producción las ejecuta GitHub Actions cada 15 minutos con `jobs/run_all.py`): "
                    "leer el buzón, completar radicaciones por API, repartir pendientes, desistimientos, cierre automático y alertas.")
    else:
        st.markdown("**Tareas programadas**: en esta demostración no corren solas; pulse el botón para ejecutarlas a la vez "
                    "(leer el buzón de correo, repartir pendientes, desistimientos, cierre automático y alertas).")
    if st.button("▶️ Ejecutar tareas ahora", type="primary"):
        with st.spinner("Ejecutando…"):
            r = S.ejecutar_tareas()
        st.success("Tareas ejecutadas.")
        st.json({k: (len(v) if isinstance(v, list) else v) for k, v in r.items()})
    st.divider()
    st.markdown("**Reiniciar datos de demostración**: borra todo y vuelve a cargar ~300 PQRS ficticias.")
    if repo.es_pg:
        st.info("Con Supabase el reinicio se hace desde el equipo técnico: `python scripts/setup_supabase.py --reset`.")
        st.stop()
    conf = st.text_input("Escriba REINICIAR para confirmar")
    if st.button("🗑 Reiniciar demo", disabled=conf != "REINICIAR"):
        from core import semilla
        with st.spinner("Recargando datos ficticios…"):
            repo.borrar_todo()
            if not repo.es_pg:
                repo.crear_esquema_sqlite()
            r = semilla.cargar(repo)
            C.limpiar_cache()
        st.success(f"Demo reiniciada: {r}")
