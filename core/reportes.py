"""Reportes R1–R9 calculados con pandas sobre las solicitudes visibles para el usuario."""
from __future__ import annotations

import io
from datetime import date

import pandas as pd

from core import flujo, plazos
from core import consultas as C
from core.reloj import a_fecha, a_fechahora, hoy as _hoy

RESPONDIDAS = {"ENVIADA", "CERRADA", "TRASLADADA", "DESISTIDA"}


def marco(filas: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(filas)
    if df.empty:
        return df
    df["f_rad"] = df["fecha_radicacion"].map(a_fecha)
    df["f_ven"] = df["fecha_vencimiento"].map(a_fecha)
    df["f_resp"] = df["fecha_respuesta"].map(a_fecha)
    df["f_rec"] = df["fecha_recepcion"].map(lambda v: a_fechahora(v))
    df["mes"] = df["f_rec"].map(lambda d: d.strftime("%Y-%m"))
    df["abierta"] = df["estado"].isin(flujo.ABIERTOS)
    df["respondida"] = df["estado"].isin(RESPONDIDAS)
    df["a_tiempo"] = df.apply(lambda r: bool(r["respondida"] and r["f_resp"] and r["f_ven"] and r["f_resp"] <= r["f_ven"]), axis=1)
    hoy = _hoy()
    df["vencida"] = df.apply(lambda r: bool(r["abierta"] and r["f_ven"] and r["f_ven"] < hoy and r["estado"] != "PENDIENTE_INFO"), axis=1)
    df["dias_respuesta"] = df.apply(lambda r: plazos.dias_habiles_entre(r["f_rad"], r["f_resp"]) if r["respondida"] and r["f_resp"] and r["f_rad"] else None, axis=1)
    return df


def r1_tablero(df: pd.DataFrame) -> pd.DataFrame:
    """R1: recibidas, abiertas, cerradas, % a tiempo, vencidas, tiempo promedio (días hábiles); por empresa y consolidado."""
    cols = ["Empresa", "Recibidas", "Abiertas", "Respondidas", "Anuladas", "% a tiempo", "Vencidas", "Promedio días hábiles"]
    if df.empty:
        return pd.DataFrame(columns=cols)

    def fila(nombre, g):
        resp = int(g["respondida"].sum())
        return {"Empresa": nombre, "Recibidas": int(len(g)), "Abiertas": int(g["abierta"].sum()), "Respondidas": resp,
                "Anuladas": int((g["estado"] == "ANULADA").sum()),
                "% a tiempo": round(100.0 * g["a_tiempo"].sum() / resp, 1) if resp else 0.0,
                "Vencidas": int(g["vencida"].sum()),
                "Promedio días hábiles": round(float(pd.to_numeric(g["dias_respuesta"], errors="coerce").mean()), 1)
                if g["dias_respuesta"].notna().any() else 0.0}
    filas = [fila(cod, g) for cod, g in df.groupby("empresa_codigo")]
    filas.append(fila("CONSOLIDADO", df))
    return pd.DataFrame(filas, columns=cols)


def r2_tipo_canal(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()
    por_tipo = df.pivot_table(index="mes", columns="tipo_nombre", values="id", aggfunc="count", fill_value=0)
    por_canal = df.pivot_table(index="mes", columns="canal", values="id", aggfunc="count", fill_value=0)
    return por_tipo, por_canal


def r3_desempeno(df: pd.DataFrame, empresa_id=None) -> pd.DataFrame:
    carga = pd.DataFrame(C.carga_equipo(empresa_id))
    if carga.empty:
        return carga
    devs = C.R().q("select r.autor_id, count(*) as n from aprobaciones a join respuestas r on r.id = a.respuesta_id "
                   "where a.decision = 'devuelta' group by r.autor_id")
    mapa = {d["autor_id"]: d["n"] for d in devs}
    filas = []
    for _, a in carga.iterrows():
        g = df[df["abogado_id"] == a["abogado_id"]] if not df.empty else df
        resp = int(g["respondida"].sum()) if not g.empty else 0
        filas.append({"Abogado": a["abogado"], "Abiertos": a["casos_abiertos"], "Carga ponderada": a["carga_ponderada"],
                      "Respondidos": resp, "% a tiempo": round(100.0 * g["a_tiempo"].sum() / resp, 1) if resp else 0.0,
                      "Devoluciones": int(mapa.get(a["abogado_id"], 0)), "Disponible": "Sí" if a["disponible"] else "No (ausente)"})
    return pd.DataFrame(filas)


def r4_vencimientos(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    ab = df[df["abierta"] & (df["estado"] != "PENDIENTE_INFO")].copy()

    def grupo(r):
        d = r["dias_restantes"]
        if d is None:
            return "Sin plazo"
        if d < 0:
            return "1. Vencidas"
        if d == 0:
            return "2. Vencen hoy"
        if d <= 2:
            return "3. En 1–2 días"
        if d <= 5:
            return "4. En 3–5 días"
        return "5. Más de 5 días"
    ab["Grupo"] = ab.apply(grupo, axis=1)
    return ab[["Grupo", "radicado", "empresa_codigo", "tipo_nombre", "abogado_nombre", "estado", "fecha_vencimiento",
               "sem_etiqueta"]].sort_values(["Grupo", "fecha_vencimiento"])


def r5_cuellos(sids: set[int]) -> pd.DataFrame:
    """Tiempo promedio (horas) que los casos pasan en cada estado, a partir de la bitácora."""
    evs = C.R().q("select solicitud_id, detalle, fecha from eventos where accion = 'cambio_estado' and solicitud_id is not null "
                  "order by solicitud_id, id")
    durac: dict[str, list[float]] = {}
    previo: dict[int, tuple[str, object]] = {}
    for e in evs:
        if e["solicitud_id"] not in sids:
            continue
        d = e["detalle"] or {}
        t = a_fechahora(e["fecha"])
        ant = previo.get(e["solicitud_id"])
        if ant and ant[0] == d.get("de"):
            durac.setdefault(ant[0], []).append((t - ant[1]).total_seconds() / 3600)
        previo[e["solicitud_id"]] = (d.get("a"), t)
    filas = [{"Estado": k, "Explicación": flujo.explicar(k), "Casos": len(v), "Horas promedio": round(sum(v) / len(v), 1)}
             for k, v in durac.items() if v]
    return pd.DataFrame(filas).sort_values("Horas promedio", ascending=False) if filas else pd.DataFrame()


def r6_temas(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return (df.groupby(["tema_nombre", "tipo_nombre"]).size().reset_index(name="Casos")
            .sort_values("Casos", ascending=False).rename(columns={"tema_nombre": "Tema", "tipo_nombre": "Tipo"}))


def r7_satisfaccion(sids: set[int]) -> pd.DataFrame:
    filas = [f for f in C.R().q("select solicitud_id, puntaje, fecha from encuestas") if f["solicitud_id"] in sids]
    return pd.DataFrame(filas)


def a_excel(hojas: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for nombre, df in hojas.items():
            (df if not df.empty else pd.DataFrame({"(sin datos)": []})).to_excel(w, sheet_name=nombre[:31], index=False)
    return buf.getvalue()


def a_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


COLUMNAS_LISTADO = {"radicado": "Radicado", "sem_etiqueta": "Semáforo", "estado_texto": "Estado", "empresa_codigo": "Empresa",
                    "tipo_nombre": "Tipo", "tema_nombre": "Tema", "asunto": "Asunto", "solicitante_nombre": "Solicitante",
                    "abogado_nombre": "Abogado", "canal": "Canal", "fecha_radicacion": "Radicación",
                    "fecha_vencimiento": "Vence"}


def listado(filas: list[dict], extra: dict | None = None) -> pd.DataFrame:
    cols = {**COLUMNAS_LISTADO, **(extra or {})}
    df = pd.DataFrame(filas)
    if df.empty:
        return pd.DataFrame(columns=list(cols.values()))
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df[list(cols)].rename(columns=cols)
