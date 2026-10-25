"""Datos de demostración FICTICIOS de TRD y archivo físico, para que todo se vea sin preparación.

Se aplican DESPUÉS de sembrar las PQRS, usando los mismos servicios que usa la aplicación (core/archivo.py):
  * TRD por empresa (serie «10 PQRS» con 5 subseries, más la serie «90 Actas de eliminación»).
  * Papel en ventanilla: ~35 % de los casos cerrados traen documentos físicos (docs_fisicos / hojas_fisicas).
  * Expedientes: ~75 % de los casos cerrados ya tienen serie; el resto queda «sin serie» para mostrar el reporte.
  * Para mostrar alertas y disposición final, las fechas de cierre de algunos expedientes se RETRODATAN (la retención se mide en
    años y los casos de la demo se cerraron hace meses). Esos expedientes lo dicen en su observación.
  * Cajas, carpetas, préstamos (uno vencido) y disposiciones en distintos estados con su acta.
"""
from __future__ import annotations

import random
from datetime import timedelta

from core import archivo as A
from core import consultas as C
from core.catalogo_demo import DOMINIO
from core.reloj import ahora, hoy as _hoy

SERIES_DEMO = [
    # código, nombre, descripción, años gestión, años central, disposición, tipos PQRS sugeridos, padre
    ("10", "PQRS · Peticiones, quejas, reclamos y sugerencias", "Serie madre: agrupa las subseries de atención al ciudadano.",
     None, None, None, "", None),
    ("10.1", "Peticiones y consultas", "Peticiones de interés general o particular y consultas.", 1, 2, "eliminar", "P,C", "10"),
    ("10.2", "Solicitudes de documentos y copias", "Solicitudes de copias, certificados y paz y salvo.", 1, 1, "eliminar", "D", "10"),
    ("10.3", "Quejas y sugerencias", "Quejas por la atención y sugerencias o felicitaciones.", 2, 3, "digitalizar", "Q,S", "10"),
    ("10.4", "Reclamos", "Reclamos por cobros, daños o fallas del servicio (pueden originar procesos).", 2, 8, "conservar", "R", "10"),
    ("10.5", "Derechos sobre datos personales", "Consulta, rectificación y supresión (Ley 1581 de 2012).", 2, 3, "eliminar", "CD,RD", "10"),
    ("90", "Actas de eliminación documental", "Actas que respaldan cada disposición final aprobada.", 5, 10, "conservar", "", None),
]
# días hasta la disposición de los expedientes retrodatados (negativo = ya vencida), repetido por empresa
PATRON_DIAS = [-45, -10, -70, 12, 25, 55, 80, -20, 140, None]


def _usuario(rol: str, cod: str):
    return C.usuario_por_email(f"{rol}.{cod.lower()}@{DOMINIO}")


def cargar(repo, semilla: int = 2026, hoy=None) -> dict:
    hoy = hoy or _hoy()
    rng = random.Random(semilla + 77)
    empresas = C.empresas()
    adm = C.usuario_por_email(f"admin@{DOMINIO}")
    res = {"series": 0, "expedientes": 0, "cajas": 0, "carpetas": 0, "prestamos": 0, "disposiciones": 0}
    # --- 1. TRD por empresa
    ids_serie: dict[int, dict[str, int]] = {}
    for e in empresas:
        ids_serie[e["id"]] = {}
        for cod, nombre, desc, g, c, disp, tipos, padre in SERIES_DEMO:
            ids_serie[e["id"]][cod] = A.guardar_serie({
                "empresa_id": e["id"], "codigo": cod, "nombre": nombre, "descripcion": desc, "anios_gestion": g, "anios_central": c,
                "disposicion": disp, "tipos_sugeridos": tipos, "serie_padre_id": ids_serie[e["id"]].get(padre) if padre else None,
                "procedimiento": "Demostración: reemplazar por el procedimiento de la TRD aprobada por el cliente."
                if cod == "10.1" else None,
                "acto_aprobacion": "TRD de demostración (sin acto administrativo)"}, adm)
            res["series"] += 1
    # --- 2. Papel en ventanilla (separado del generador de PQRS para no alterar sus datos)
    cerradas = repo.q("select id, empresa_id from solicitudes where estado = 'CERRADA' order by empresa_id, radicado")
    for s in cerradas:
        if rng.random() < (0.5 if s["empresa_id"] == 1 else 0.3):
            repo.actualizar("solicitudes", s["id"], {"docs_fisicos": True, "hojas_fisicas": rng.randint(3, 40)})
    C.limpiar_cache()
    # --- 3. Expedientes
    for e in empresas:
        arch = _usuario("archivista", e["codigo"])
        propios = [s for s in cerradas if s["empresa_id"] == e["id"]]
        j = 0
        for i, s in enumerate(propios):
            if i % 4 == 3:
                continue  # queda sin serie
            sol = C.obtener_solicitud(s["id"], sin_alcance=True)
            st_ = A.sugerir_serie(sol, arch)
            if not st_:
                continue
            dias = PATRON_DIAS[j % len(PATRON_DIAS)]
            j += 1
            real = A._fecha_cierre(sol)
            if dias is None:
                A._crear_expediente(sol, st_, arch, real)
            else:
                objetivo = hoy + timedelta(days=dias)
                cierre = A.sumar_anios(objetivo, -(st_["anios_gestion"] + st_["anios_central"]))
                A._crear_expediente(sol, st_, arch, cierre,
                                    observacion="DEMO: fecha de cierre retrodatada para mostrar alertas de vencimiento.")
            res["expedientes"] += 1
    # --- 4. Cajas y carpetas (solo los expedientes con papel)
    for e in empresas:
        arch = _usuario("archivista", e["codigo"])
        fisicos = [x for x in A.expedientes(arch, e["id"]) if x["docs_fisicos"]]
        por_serie: dict[int, list[dict]] = {}
        for x in fisicos:
            por_serie.setdefault(x["serie_id"], []).append(x)
        caja_id, n_caja = None, 0
        for serie_id, xs in por_serie.items():
            for k in range(0, len(xs), 2):
                grupo = xs[k:k + 2]
                if caja_id is None or R_llena(repo, caja_id):
                    n_caja += 1
                    caja_id = A.crear_caja({
                        "empresa_id": e["id"], "sede": "Sede principal", "deposito": "Archivo central",
                        "estante": f"E-{(n_caja - 1) // 3 + 1:02d}", "entrepano": f"N{(n_caja - 1) % 3 + 1}", "capacidad_carpetas": 4}, arch)
                    res["cajas"] += 1
                fid = A.crear_carpeta(caja_id, arch, serie_id, a_fecha_anio(grupo[0]),
                                      f"{grupo[0]['serie_nombre']} · {len(grupo)} expediente(s)")
                res["carpetas"] += 1
                for x in grupo:
                    A.ubicar_expediente(x["id"], fid, arch)
        # primera caja llena: se cierra (ejemplo de caja cerrada)
        llenas = [c for c in A.cajas(arch, e["id"]) if c["n_carpetas"] >= c["capacidad_carpetas"]]
        if llenas:
            A.cerrar_caja(llenas[0]["id"], arch)
        # una caja vacía reservada para el próximo lote
        A.crear_caja({"empresa_id": e["id"], "sede": "Sede principal", "deposito": "Archivo central",
                      "estante": f"E-{n_caja // 3 + 1:02d}", "entrepano": f"N{n_caja % 3 + 1}", "capacidad_carpetas": 4,
                      "observaciones": "Reservada para el próximo lote"}, arch)
        res["cajas"] += 1
    # --- 5. Disposición final en distintos estados (EMP01 y EMP02: propuesta, revisada, aprobada con acta y ejecutada)
    for e in empresas[:2]:
        arch, sup = _usuario("archivista", e["codigo"]), _usuario("supervisor", e["codigo"])
        vencidos = [x for x in A.expedientes(arch, e["id"]) if x["estado"] == "activo" and x["dias_restantes"] < 0][:4]
        if not vencidos:
            continue
        A.proponer_disposiciones(arch, e["id"], [x["id"] for x in vencidos])
        res["disposiciones"] += len(vencidos)
        ds = {d["expediente_id"]: d for d in A.disposiciones(arch, empresa_id=e["id"])}
        orden = [ds[x["id"]] for x in vencidos if x["id"] in ds]
        for d in orden[1:4]:  # la primera queda solo «propuesta»
            A.revisar_disposicion(d["id"], True, "Revisados los folios y la serie: coincide con la TRD vigente (demostración).", arch)
        if len(orden) >= 3:
            A.decidir_disposiciones([d["id"] for d in orden[2:4]], True, "Aprobada la disposición según la TRD de demostración.", sup)
        if len(orden) >= 4:
            A.ejecutar_disposicion(orden[3]["id"], "Registro de la ejecución (demostración: no se borró nada).", arch)
    # --- 6. Préstamos (EMP01)
    e1 = empresas[0]
    arch, sup = _usuario("archivista", e1["codigo"]), _usuario("supervisor", e1["codigo"])
    abog = C.usuario_por_email(f"abogado1.{e1['codigo'].lower()}@{DOMINIO}")
    libres = [c for c in A.carpetas(arch, e1["id"]) if c["estado"] == "en_archivo" and c["n_expedientes"]]
    if len(libres) >= 4:
        p0 = A.solicitar_prestamo(libres[0]["id"], "Revisión del expediente para responder un recurso del ciudadano", 5, abog)
        A.entregar_prestamo(p0, arch)
        repo.actualizar("archivo_prestamos", p0, {"fecha_prestamo": ahora() - timedelta(days=12), "fecha_vence": hoy - timedelta(days=7)})
        p1 = A.solicitar_prestamo(libres[1]["id"], "Consulta de antecedentes para un caso nuevo", 8, sup)
        A.entregar_prestamo(p1, arch)
        p2 = A.solicitar_prestamo(libres[2]["id"], "Verificación de soportes para auditoría interna", 3, abog)
        A.entregar_prestamo(p2, arch)
        A.devolver_prestamo(p2, arch, "Devuelta completa, 100 % de folios verificados.")
        A.solicitar_prestamo(libres[3]["id"], "Copia de soportes solicitada por el supervisor", 4, sup)
        res["prestamos"] = 4
    # EMP02: un préstamo vigente, para que se vea el aislamiento también en los préstamos
    e2 = empresas[1]
    arch2, sup2 = _usuario("archivista", e2["codigo"]), _usuario("supervisor", e2["codigo"])
    libres2 = [c for c in A.carpetas(arch2, e2["id"]) if c["estado"] == "en_archivo" and c["n_expedientes"]]
    if libres2:
        p5 = A.solicitar_prestamo(libres2[0]["id"], "Consulta de antecedentes para una auditoría interna", 6, sup2)
        A.entregar_prestamo(p5, arch2)
        res["prestamos"] += 1
    C.limpiar_cache()
    return res


def R_llena(repo, caja_id: int) -> bool:
    c = repo.q("select capacidad_carpetas, (select count(*) from archivo_carpetas where caja_id = archivo_cajas.id) as n "
               "from archivo_cajas where id = ?", [caja_id], uno=True)
    return c["n"] >= c["capacidad_carpetas"]


def a_fecha_anio(x: dict) -> int:
    """Año del radicado (el de la PQRS), no el de la fecha de cierre retrodatada."""
    import re
    m = re.search(r"(20\d\d)", x["radicado"])
    return int(m.group(1)) if m else _hoy().year
