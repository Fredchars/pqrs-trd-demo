"""Catálogos FICTICIOS de la beta: empresas, usuarios, tipos, temas, plantillas y parámetros.

Fuente única para el modo demo (SQLite) y para db/04_datos_demo.sql (scripts/generar_sql_demo.py).
"""
from __future__ import annotations

import uuid

DOMINIO = "pqrs.example.com"   # dominio reservado (RFC 2606): ningún correo llega a personas reales
CLAVE_DEMO = "DemoPQRS-2026!"  # contraseña compartida de los usuarios ficticios en Supabase Auth
CODIGO_CONSULTA_DEMO = "DEMO2026"  # código de consulta de los casos precargados

EMPRESAS = [
    ("EMP01", "Aguas del Litoral S.A. E.S.P. (ficticia)", "agua", "#0E6BA8"),
    ("EMP02", "Energía Costera S.A. E.S.P. (ficticia)", "energía", "#B45309"),
    ("EMP03", "Transportes Bahía S.A.S. (ficticia)", "transporte", "#047857"),
    ("EMP04", "Gas del Norte S.A. E.S.P. (ficticia)", "gas", "#9D174D"),
    ("EMP05", "Aseo Urbano S.A. E.S.P. (ficticia)", "aseo", "#4D7C0F"),
    ("EMP06", "Telecom Litoral S.A.S. (ficticia)", "internet", "#6D28D9"),
    ("EMP07", "Puertos y Logística S.A. (ficticia)", "servicio portuario", "#0F766E"),
    ("EMP08", "Vías del Mar Concesión S.A.S. (ficticia)", "peaje", "#A16207"),
    ("EMP09", "Salud Integral IPS S.A.S. (ficticia)", "cita médica", "#BE123C"),
    ("EMP10", "Inmobiliaria Consorcio S.A.S. (ficticia)", "arriendo", "#1E40AF"),
]

TIPOS = [
    # codigo, nombre, descripción en lenguaje claro, ejemplo de una línea, días, prórroga máx, peso, niveles, palabras clave, referencia
    ("P", "Petición", "Pedir algo a la empresa: una actuación, una explicación o una solución.",
     "Ej.: «Solicito que revisen el servicio en mi barrio».", 15, None, 1.0, 1,
     "solicito,peticion,derecho de peticion,les pido,requiero", "Ley 1755 de 2015"),
    ("D", "Solicitud de documentos o información", "Pedir copias, certificados o información que tiene la empresa.",
     "Ej.: «Necesito copia de mis facturas de 2025».", 10, None, 1.0, 1,
     "copia,certificado,documento,historial,informacion", "Ley 1755 de 2015"),
    ("C", "Consulta", "Pedir la opinión o el concepto de la empresa sobre un tema.",
     "Ej.: «¿Qué requisitos hay para trasladar el servicio?»", 30, None, 2.0, 1,
     "consulta,concepto,requisitos,como puedo,pregunta", "Ley 1755 de 2015"),
    ("Q", "Queja", "Contar una inconformidad con la atención o el trato recibido.",
     "Ej.: «Me atendieron de mala manera en la oficina».", 15, None, 1.0, 1,
     "queja,mala atencion,trato,grosero,demora", "Política interna / Ley 1755"),
    ("R", "Reclamo", "Pedir que se corrija un problema con el servicio o un cobro.",
     "Ej.: «Me cobraron dos veces el mismo mes».", 15, None, 1.5, 1,
     "reclamo,cobro,doble cobro,devolucion,falla,dano,factura alta", "Ley 1755; Ley 1480 si es de consumo"),
    ("S", "Sugerencia o felicitación", "Proponer una mejora o felicitar al equipo.",
     "Ej.: «Sería útil pagar por la aplicación».", 15, None, 0.5, 0,
     "sugerencia,sugiero,felicito,felicitacion,propongo", "Política interna"),
    ("CD", "Consulta de datos personales", "Saber qué datos suyos tiene la empresa y para qué los usa.",
     "Ej.: «¿Qué datos míos tienen registrados?»", 10, 5, 1.5, 1,
     "mis datos,habeas data,datos personales,que datos", "Ley 1581 de 2012"),
    ("RD", "Reclamo de datos personales", "Pedir que corrijan, actualicen o borren sus datos personales.",
     "Ej.: «Quiero que eliminen mi número de su base».", 15, 8, 1.5, 1,
     "supresion,rectificacion,eliminen mis datos,revocar autorizacion,borrar mis datos", "Ley 1581 de 2012"),
]

TEMAS = [  # nombre, especialidad requerida, sensible
    ("Facturación y cobros", None, False),
    ("Calidad del servicio", None, False),
    ("Atención al usuario", None, False),
    ("Contratos y garantías", "contratos", False),
    ("Datos personales", "datos_personales", True),
    ("Asuntos laborales", "laboral", True),
]

NOMBRES = ["Andrea", "Carlos", "Diana", "Esteban", "Fernanda", "Gustavo", "Helena", "Iván", "Juliana", "Kevin", "Laura",
           "Mauricio", "Natalia", "Óscar", "Paola", "Ricardo", "Sofía", "Tomás", "Valentina", "Wilson", "Ximena", "Yesid",
           "Zulma", "Camilo", "Daniela", "Felipe", "Gloria", "Hernán", "Isabel", "Jorge"]
APELLIDOS = ["Arrieta", "Barrios", "Cárdenas", "Díaz", "Escorcia", "Fuentes", "Guerra", "Herrera", "Ibáñez", "Jiménez",
             "Lozano", "Martínez", "Navarro", "Orozco", "Pérez", "Quintero", "Rojas", "Suárez", "Torres", "Urrutia",
             "Vergara", "Zapata", "Castro", "Mendoza", "Ospina", "Padilla", "Romero", "Salgado", "Toro", "Villa"]


def auth_uuid(email: str) -> str:
    """UUID determinista para enlazar el usuario con Supabase Auth."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"pqrs-beta:{email.lower()}"))


def empresas() -> list[dict]:
    return [{"id": i, "codigo": c, "nombre": n, "nit": f"900.{100 + i:03d}.{200 + i:03d}-{i % 10} (ficticio)",
             "buzon_correo": f"pqrs.{c.lower()}@{DOMINIO}", "logo_url": None, "color": color,
             "estrategia_reparto": "E", "acepta_anonimas": True, "activo": True}
            for i, (c, n, _s, color) in enumerate(EMPRESAS, start=1)]


def tipos() -> list[dict]:
    return [{"id": i, "codigo": c, "nombre": n, "descripcion": d, "ejemplo": e, "dias_habiles": dias,
             "dias_prorroga_max": pr, "peso_carga": peso, "niveles_aprobacion": niv, "palabras_clave": pc,
             "referencia": ref, "activo": True}
            for i, (c, n, d, e, dias, pr, peso, niv, pc, ref) in enumerate(TIPOS, start=1)]


def temas() -> list[dict]:
    filas, i = [], 1
    for emp in range(1, len(EMPRESAS) + 1):
        for nombre, esp, sens in TEMAS:
            filas.append({"id": i, "empresa_id": emp, "nombre": nombre, "especialidad_requerida": esp, "sensible": sens})
            i += 1
    return filas


def usuarios() -> tuple[list[dict], list[dict]]:
    """Devuelve (usuarios, usuario_empresa)."""
    us, ue = [], []
    k = 0

    def nombre():
        nonlocal k
        n = f"{NOMBRES[k % len(NOMBRES)]} {APELLIDOS[(k * 7) % len(APELLIDOS)]}"
        k += 1
        return n

    def add(email, rol, cargo, esp=None, empresas_=(), **extra):
        uid = len(us) + 1
        us.append({"id": uid, "auth_id": auth_uuid(email), "nombre": nombre() + " (ficticio)", "email": email, "rol": rol,
                   "cargo": cargo, "especialidades": esp or [], "capacidad_max": 40, "disponible": True,
                   "ausente_desde": None, "ausente_hasta": None, "suplente_id": None, "activo": True, **extra})
        ue.extend({"usuario_id": uid, "empresa_id": e} for e in empresas_)
        return uid

    todas = list(range(1, len(EMPRESAS) + 1))
    add(f"admin@{DOMINIO}", "admin", "Administrador(a) del sistema", empresas_=todas)
    add(f"director@{DOMINIO}", "director", "Director(a) jurídico(a) del consorcio", empresas_=todas)
    add(f"auditor@{DOMINIO}", "auditor", "Auditor(a) interno(a)", empresas_=todas)
    add(f"integracion@{DOMINIO}", "integracion", "Usuario técnico de integración (API/MCP)", empresas_=todas)
    for e, (cod, *_r) in enumerate(EMPRESAS, start=1):
        c = cod.lower()
        a1 = add(f"abogado1.{c}@{DOMINIO}", "abogado", "Abogado(a) del área jurídica", ["general", "datos_personales"], [e])
        add(f"abogado2.{c}@{DOMINIO}", "abogado", "Abogado(a) del área jurídica", ["general", "contratos"], [e])
        add(f"abogado3.{c}@{DOMINIO}", "abogado", "Abogado(a) del área jurídica", ["general", "laboral"], [e])
        add(f"supervisor.{c}@{DOMINIO}", "supervisor", "Supervisor(a) jurídico(a)", empresas_=[e], suplente_id=a1)
        add(f"radicador.{c}@{DOMINIO}", "radicador", "Radicador(a) de ventanilla", empresas_=[e])
    # Archivistas (módulos TRD y archivo físico). Van al final para no cambiar los id de los usuarios anteriores.
    for e, (cod, *_r) in enumerate(EMPRESAS, start=1):
        add(f"archivista.{cod.lower()}@{DOMINIO}", "archivista", "Archivista (personal del cliente)", empresas_=[e])
    add(f"archivista.multi@{DOMINIO}", "archivista", "Archivista de varias empresas (EMP01 a EMP03)", empresas_=[1, 2, 3])
    return us, ue


def parametros() -> list[dict]:
    p = [
        ("hora_corte", "17:00", "Hora de corte: lo recibido después se radica el siguiente día hábil"),
        ("umbral_amarillo", "50", "% del plazo consumido para pasar a amarillo (y alerta al 50 %)"),
        ("umbral_rojo", "80", "% del plazo consumido para pasar a rojo (y alerta al 80 %)"),
        ("max_mb_archivo", "10", "Tamaño máximo por archivo (MB)"),
        ("max_mb_solicitud", "25", "Tamaño máximo por solicitud (MB)"),
        ("capacidad_max_defecto", "40", "Tope de casos abiertos para abogados nuevos . "
         "Cada abogado se ajusta en Administración › Usuarios (columna capacidad_max)"),
        ("ventana_duplicados_dias", "5", "Días hacia atrás para detectar posibles duplicados"),
        ("criterio_suspension", "reiniciar", "Al aportar información: «reiniciar» el término o «reanudar» lo que quedaba"),
        ("dias_desistimiento", "30", "Días calendario (≈1 mes) para aportar información antes del desistimiento"),
        ("asignar_al_radicar", "si", "Repartir en el momento de radicar (si/no). Si es no, lo hace la tarea programada"),
        ("dias_cierre_auto", "2", "Días hábiles tras el envío para cerrar automáticamente"),
        ("anonimas_solo_quejas", "si", "Si se aceptan anónimas, solo para quejas (si/no)"),
        ("alertas_por_correo", "si", "Enviar también por correo las alertas internas (si/no)"),
        ("encuesta_activa", "si", "Ofrecer encuesta de satisfacción tras la respuesta (si/no)"),
        ("palabras_spam", "casino,criptomoneda,ganaste un premio,loteria,inversion garantizada,gana dinero",
         "Palabras que mandan un correo a cuarentena"),
        ("remitentes_bloqueados", "spam@spam.example", "Remitentes que van a cuarentena"),
        ("empresa_por_defecto", "EMP01", "Empresa para correos que llegan al buzón general"),
        ("buzon_general", f"pqrs.consorcio@{DOMINIO}", "Buzón general del consorcio (variante B2)"),
    ]
    return [{"clave": c, "valor": v, "descripcion": d} for c, v, d in p]


PIE = "\n\n— Mensaje de PRUEBA de un prototipo beta con datos ficticios. No responda con datos reales."

PLANTILLAS = [
    ("acuse", "Acuse de recibo", "Recibimos su solicitud",
     "Hola {{nombre}}:\n\nRecibimos su solicitud en {{empresa}}.\n\nNúmero de radicado: {{radicado}}\n"
     "Código de consulta: {{codigo}}\nFecha de radicación: {{fecha_radicacion}}\n"
     "Fecha máxima de respuesta: {{fecha_vencimiento}}\n\nConsulte el estado en {{enlace_consulta}} con su radicado y código."
     "{{texto}}\n\nPara agregar información, responda este correo sin cambiar el asunto." + PIE),
    ("solicitud_info", "Solicitud de información", "Necesitamos información adicional",
     "Hola {{nombre}}:\n\nPara responder su solicitud {{radicado}} necesitamos lo siguiente:\n\n{{texto}}\n\n"
     "Mientras tanto el plazo de respuesta queda suspendido. Puede enviarla hasta el {{nueva_fecha}} respondiendo este "
     "correo o desde {{enlace_consulta}}. Si no la recibimos, la solicitud se cerrará por desistimiento.\n\n{{abogado}}\n{{cargo}}" + PIE),
    ("info_recibida", "Confirmación de información recibida", "Recibimos la información",
     "Hola {{nombre}}:\n\nRecibimos la información de su solicitud {{radicado}}. El plazo se reanudó y la nueva fecha "
     "máxima de respuesta es {{fecha_vencimiento}}." + PIE),
    ("prorroga", "Aviso de prórroga", "Ampliación del plazo de respuesta",
     "Hola {{nombre}}:\n\nPor el siguiente motivo necesitamos más tiempo para responder su solicitud {{radicado}}:\n\n"
     "{{motivo}}\n\nLa nueva fecha máxima de respuesta es {{nueva_fecha}}.\n\n{{abogado}}\n{{cargo}}" + PIE),
    ("traslado", "Traslado por competencia", "Su solicitud fue remitida a la entidad competente",
     "Hola {{nombre}}:\n\nRevisamos su solicitud {{radicado}} y el tema le corresponde a {{entidad}}. Por eso se la "
     "remitimos.\n\nMotivo: {{motivo}}\n\n{{abogado}}\n{{cargo}}" + PIE),
    ("traslado_interno", "Traslado entre empresas del consorcio", "Su solicitud pasó a otra empresa del consorcio",
     "Hola {{nombre}}:\n\nSu solicitud {{radicado}} será atendida por {{entidad}}, también del consorcio. Conserva el "
     "mismo número de radicado.\n\nMotivo: {{motivo}}" + PIE),
    ("desistimiento", "Cierre por desistimiento", "Cierre de su solicitud",
     "Hola {{nombre}}:\n\nNo recibimos la información solicitada para el radicado {{radicado}}, así que la solicitud se "
     "cierra por desistimiento. Puede presentar una nueva cuando quiera." + PIE),
    ("respuesta_enviada", "Envío de la respuesta", "Respuesta a su solicitud",
     "Hola {{nombre}}:\n\nAdjuntamos la respuesta a su solicitud {{radicado}} en PDF. También puede verla en "
     "{{enlace_consulta}}.\n\nCódigo de verificación del documento: {{codigo}}" + PIE),
    ("respuesta", "Respuesta general", None,
     "Cartagena, {{fecha_radicacion}}\n\nSeñor(a)\n{{nombre}}\n\nAsunto: respuesta a su {{tipo}} radicada con el número "
     "{{radicado}} («{{asunto}}»).\n\nCordial saludo:\n\nEn atención a su solicitud, le informamos que [escriba aquí la "
     "respuesta de fondo, clara y completa].\n\nSi tiene dudas, puede escribirnos citando el número de radicado.\n\n"
     "Atentamente,"),
    ("respuesta", "Reclamo procedente", None,
     "Señor(a) {{nombre}}:\n\nRevisamos su reclamo {{radicado}} sobre «{{asunto}}». Encontramos que tiene razón: "
     "[describa la corrección realizada, el valor ajustado o la acción tomada].\n\nLamentamos las molestias.\n\nAtentamente,"),
    ("respuesta", "Reclamo no procedente", None,
     "Señor(a) {{nombre}}:\n\nRevisamos su reclamo {{radicado}} sobre «{{asunto}}». Después de verificar [describa la "
     "verificación], no encontramos un error, por las siguientes razones: [explique en lenguaje claro].\n\n"
     "Si no está de acuerdo, puede presentar los recursos que la ley le permite.\n\nAtentamente,"),
    ("respuesta", "Agradecimiento por sugerencia", None,
     "Señor(a) {{nombre}}:\n\nGracias por su mensaje {{radicado}}. Lo compartimos con el área responsable de {{empresa}} "
     "para tenerlo en cuenta en nuestros planes de mejora.\n\nAtentamente,"),
]


def plantillas() -> list[dict]:
    return [{"id": i, "empresa_id": None, "tipo_id": None, "clave": c, "nombre": n, "asunto": a, "cuerpo": b, "activo": True}
            for i, (c, n, a, b) in enumerate(PLANTILLAS, start=1)]


def festivos_extra() -> list[dict]:
    return [
        {"id": 1, "empresa_id": None, "fecha": "2026-12-24", "descripcion": "Jornada interna de cierre de año (ficticia)"},
        {"id": 2, "empresa_id": None, "fecha": "2026-12-31", "descripcion": "Jornada interna de cierre de año (ficticia)"},
        {"id": 3, "empresa_id": 3, "fecha": "2026-11-20", "descripcion": "Aniversario de Transportes Bahía (ficticio)"},
    ]
