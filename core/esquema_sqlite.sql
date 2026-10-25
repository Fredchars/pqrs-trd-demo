-- Esquema SQLite equivalente a db/01_esquema.sql (modo demo local, sin configuración).
PRAGMA foreign_keys = ON;
create table if not exists empresas (id integer primary key, codigo text not null unique, nombre text not null, nit text,
  buzon_correo text, logo_url text, color text default '#1F3A5F', estrategia_reparto text not null default 'E',
  acepta_anonimas integer not null default 0, activo integer not null default 1);
create table if not exists usuarios (id integer primary key, auth_id text unique, nombre text not null, email text not null unique,
  rol text not null check (rol in ('abogado','supervisor','director','admin','radicador','auditor','integracion','archivista')),
  cargo text, especialidades text not null default '[]', capacidad_max integer not null default 40,
  disponible integer not null default 1, ausente_desde text, ausente_hasta text, suplente_id integer references usuarios(id),
  activo integer not null default 1);
create table if not exists usuario_empresa (usuario_id integer not null references usuarios(id) on delete cascade,
  empresa_id integer not null references empresas(id) on delete cascade, primary key (usuario_id, empresa_id));
create table if not exists tipos_pqrs (id integer primary key, codigo text not null unique, nombre text not null, descripcion text,
  ejemplo text, dias_habiles integer not null, dias_prorroga_max integer, peso_carga real not null default 1.0,
  niveles_aprobacion integer not null default 1, palabras_clave text, referencia text, activo integer not null default 1);
create table if not exists temas (id integer primary key, empresa_id integer not null references empresas(id), nombre text not null,
  especialidad_requerida text, sensible integer not null default 0);
create table if not exists solicitantes (id integer primary key, tipo_doc text, num_doc text, nombre text, email text, telefono text,
  direccion text, anonimo integer not null default 0, autoriza_datos integer not null default 0, fecha_autorizacion text);
create table if not exists solicitudes (id integer primary key, radicado text not null unique, empresa_id integer not null references empresas(id),
  tipo_id integer not null references tipos_pqrs(id), tema_id integer references temas(id), solicitante_id integer references solicitantes(id),
  canal text not null check (canal in ('web','correo','presencial','telefonico','api','mcp')), asunto text not null, descripcion text,
  estado text not null default 'RECIBIDA' check (estado in ('RECIBIDA','ASIGNADA','EN_TRAMITE','PENDIENTE_INFO','EN_REVISION','APROBADA',
  'ENVIADA','CERRADA','REABIERTA','ANULADA','TRASLADADA','DESISTIDA')), prioridad text not null default 'normal',
  fecha_recepcion text not null, fecha_radicacion text, fecha_vencimiento text, dias_suspendidos integer not null default 0,
  suspendida_desde text, prorrogada integer not null default 0, fecha_respuesta text, abogado_id integer references usuarios(id),
  solicitud_padre_id integer references solicitudes(id), posible_duplicado_de integer references solicitudes(id),
  revisar_duplicado integer not null default 0, respuesta_parcial integer not null default 0, reabierta integer not null default 0,
  empresa_origen_id integer references empresas(id), entidad_traslado text, marca text, codigo_consulta text, message_id text,
  creado_por integer references usuarios(id), pendiente_completar integer not null default 0,
  docs_fisicos integer not null default 0, hojas_fisicas integer not null default 0);
create unique index if not exists uq_solicitudes_id_empresa on solicitudes (id, empresa_id);
create index if not exists ix_sol_empresa_estado on solicitudes (empresa_id, estado);
create index if not exists ix_sol_abogado on solicitudes (abogado_id);
create table if not exists asignaciones (id integer primary key, solicitud_id integer not null references solicitudes(id),
  abogado_id integer references usuarios(id), motivo text not null check (motivo in ('automatica','manual','ausencia','traslado','rechazo','cola')),
  detalle text, asignado_por integer references usuarios(id), fecha text not null);
create table if not exists respuestas (id integer primary key, solicitud_id integer not null references solicitudes(id), version integer not null,
  contenido text not null, es_parcial integer not null default 0,
  estado text not null default 'borrador' check (estado in ('borrador','en_revision','devuelta','aprobada','enviada')),
  autor_id integer references usuarios(id), origen text not null default 'app', fecha text not null, actualizado text not null,
  unique (solicitud_id, version));
create table if not exists aprobaciones (id integer primary key, respuesta_id integer not null references respuestas(id), nivel integer not null,
  aprobador_id integer references usuarios(id), decision text not null check (decision in ('aprobada','devuelta')), comentario text,
  urgente integer not null default 0, fecha text not null);
create table if not exists documentos (id integer primary key, solicitud_id integer not null references solicitudes(id),
  categoria text not null check (categoria in ('entrada','trabajo','respuesta','soporte')), nombre text not null, nombre_original text,
  ruta text not null, mime text, tamano integer, sha256 text not null, version integer not null default 1, texto_extraido text,
  estado_texto text, subido_por integer references usuarios(id), origen text default 'app', fecha text not null);
create table if not exists alertas (id integer primary key, solicitud_id integer references solicitudes(id), destinatario text,
  destinatario_id integer references usuarios(id), rol_destino text, canal text not null default 'app+correo', tipo text not null,
  mensaje text, clave text unique, programada_para text not null, enviada_en text, leida integer not null default 0,
  estado text not null default 'pendiente', error text, empresa_id integer references empresas(id),
  check (solicitud_id is null or empresa_id is not null),
  foreign key (solicitud_id, empresa_id) references solicitudes(id, empresa_id) on update cascade);
create index if not exists ix_alertas_empresa on alertas (empresa_id);
create table if not exists plantillas (id integer primary key, empresa_id integer references empresas(id), tipo_id integer references tipos_pqrs(id),
  clave text not null, nombre text not null, asunto text, cuerpo text not null, activo integer not null default 1);
create table if not exists eventos (id integer primary key, solicitud_id integer references solicitudes(id), usuario_id integer references usuarios(id),
  origen text not null default 'app', accion text not null, detalle text, fecha text not null, empresa_id integer references empresas(id),
  check (solicitud_id is null or empresa_id is not null),
  foreign key (solicitud_id, empresa_id) references solicitudes(id, empresa_id) on update cascade);
create index if not exists ix_eventos_sol on eventos (solicitud_id, fecha);
create index if not exists ix_eventos_empresa on eventos (empresa_id);
-- Solo inserción. Única excepción: cambiar empresa_id (cascada de la clave foránea al trasladar un caso de empresa).
create trigger if not exists tr_eventos_no_update before update on eventos
  when new.id is not old.id or new.solicitud_id is not old.solicitud_id or new.usuario_id is not old.usuario_id
    or new.origen is not old.origen or new.accion is not old.accion or new.detalle is not old.detalle or new.fecha is not old.fecha
  begin select raise(abort, 'La bitácora (eventos) es de solo inserción: no se puede modificar ni borrar.'); end;
create trigger if not exists tr_eventos_no_delete before delete on eventos
  begin select raise(abort, 'La bitácora (eventos) es de solo inserción: no se puede modificar ni borrar.'); end;
create table if not exists consecutivos (empresa_id integer not null references empresas(id), anio integer not null,
  ultimo integer not null default 0, primary key (empresa_id, anio));
create table if not exists festivos_extra (id integer primary key, empresa_id integer references empresas(id), fecha text not null, descripcion text);
create table if not exists correos_procesados (message_id text primary key, fecha text not null, solicitud_id integer references solicitudes(id));
create table if not exists parametros (clave text primary key, valor text, descripcion text);
create table if not exists correos (id integer primary key, direccion text not null check (direccion in ('entrada','salida')),
  modo text not null default 'simulado', message_id text, de text, para text, asunto text, cuerpo text, eml text,
  solicitud_id integer references solicitudes(id), estado text not null default 'pendiente', error text, fecha text not null,
  empresa_id integer references empresas(id), check (solicitud_id is null or empresa_id is not null),
  foreign key (solicitud_id, empresa_id) references solicitudes(id, empresa_id) on update cascade);
create index if not exists ix_correos_empresa on correos (empresa_id);
create table if not exists filtros_guardados (id integer primary key, usuario_id integer not null references usuarios(id), nombre text not null,
  filtros text not null, fecha text not null);
create table if not exists encuestas (id integer primary key, solicitud_id integer not null unique references solicitudes(id),
  puntaje integer not null check (puntaje between 1 and 5), comentario text, fecha text not null);
-- Índice de texto completo (equivalente a tsvector + unaccent): quita tildes al indexar y al buscar.
create virtual table if not exists busqueda_fts using fts5(texto, solicitud_id unindexed, origen unindexed, ref_id unindexed,
  tokenize = 'unicode61 remove_diacritics 2');
