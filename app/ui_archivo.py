"""Piezas comunes de las pantallas de TRD y archivo físico."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import tema
import ui
from core import archivo as A
from core import consultas as C
from core.reloj import fmt_fecha

TONO_NIVEL = {"vencida": "rojo", "30": "naranja", "90": "amarillo", None: "verde"}
ICONO_DISP = {k: f"{A.DISPOSICION_ICONO[k]} {v}" for k, v in A.DISPOSICIONES.items()}


def empresas_visibles(u: dict) -> list[dict]:
    if u["rol"] in ("admin", "auditor"):
        return C.empresas()
    return [e for e in (C.empresa(i) for i in u.get("empresas", [])) if e]


def selector_empresa(u: dict, key: str = "emp_arch", ayuda: str = "") -> dict:
    """Empresa de trabajo. Si el usuario solo tiene una, se muestra fija (sin pedir nada)."""
    emps = empresas_visibles(u)
    if not emps:
        st.warning("Su usuario no tiene empresas asignadas. Pida al administrador que se las asigne.")
        st.stop()
    if len(emps) == 1:
        ui.encabezado_empresa(emps[0], ayuda or "Empresa de trabajo")
        return emps[0]
    return st.selectbox("🏢 Empresa de trabajo", emps, format_func=lambda e: f"{e['codigo']} · {e['nombre']}", key=key,
                        help="Cada empresa tiene su propia TRD, sus cajas y sus préstamos. Nada se mezcla entre empresas.")


def df_expedientes(filas: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{
        "Radicado": x["radicado"], "Serie": f"{x['serie_codigo']} · {x['serie_nombre']}",
        "Cierre": fmt_fecha(x["fecha_cierre"]), "Vence retención": fmt_fecha(x["fecha_disposicion"]),
        "Días": x["dias_restantes"], "Alerta": f"{x['nivel_icono']} {x['nivel_texto']}",
        "Disposición": ICONO_DISP.get(x["disposicion"], x["disposicion"]), "Folios": x["folios"],
        "Ubicación": (f"{x['caja_codigo']} / {x['carpeta_codigo']}" if x.get("carpeta_codigo") else "Sin ubicar"),
        "Estado": A.ESTADOS_EXPEDIENTE.get(x["estado"], x["estado"]),
    } for x in filas])


def vista_vacia(icono: str, titulo: str, texto: str):
    tema.vacio(icono, titulo, texto)


def solo_lectura(u: dict) -> bool:
    return u["rol"] not in A.ROLES_GESTION


def aviso_permiso(u: dict, accion: str):
    if solo_lectura(u):
        st.caption(f"🔒 Su rol ({C.ROLES.get(u['rol'], u['rol'])}) puede consultar, pero no {accion}. Eso lo hace el archivista.")


def ejecutar(fn, ok: str, *args, **kw):
    """Corre una operación del archivo mostrando el resultado de forma amable."""
    try:
        r = fn(*args, **kw)
        st.session_state["flash"] = ok
        return r if r is not None else True
    except A.ErrorArchivo as e:
        st.error(f"⚠️ {e}")
    except Exception as e:  # pragma: no cover
        ui.error(e)
    return None


def mostrar_flash():
    m = st.session_state.pop("flash", None)
    if m:
        st.success(m)


def indice_tabla(filas: list[dict]):
    """Índice del expediente listo para mostrar (columnas legibles). Tolera valores vacíos (None/NaN) de pandas."""
    import pandas as pd
    ind = pd.DataFrame(filas)
    if ind.empty:
        return ind
    def txt(v, f=lambda t: t):
        return f(v) if isinstance(v, str) and v else "—"
    ind["fecha_doc"] = ind["fecha_doc"].map(lambda v: txt(v, fmt_fecha))
    ind["soporte"] = ind["soporte"].map({"electronico": "💻 Electrónico", "fisico": "📄 Papel"}).fillna("—")
    ind["folios_txt"] = ind.apply(lambda r: f"{int(r['folio_inicial'])}–{int(r['folio_final'])}"
                                  if pd.notna(r["folio_inicial"]) and r["folio_inicial"] else str(r["folios"]), axis=1)
    ind["sha"] = ind["sha256"].map(lambda v: txt(v, lambda t: t[:16] + "…"))
    return ind.rename(columns={"orden": "N.º", "descripcion": "Documento", "fecha_doc": "Fecha", "folios_txt": "Folios",
                               "soporte": "Soporte", "sha": "Huella SHA-256"})[["N.º", "Documento", "Fecha", "Folios", "Soporte", "Huella SHA-256"]]
