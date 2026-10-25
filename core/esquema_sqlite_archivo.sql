-- Esquema SQLite equivalente a db/06_trd_archivo.sql (módulos TRD y archivo físico, modo demo local). Idempotente.
create table if not exists trd_series (id integer primary key, empresa_id integer not null references empresas(id),
  codigo text not null, nombre text not null, descripcion text, serie_padre_id integer,
  anios_gestion integer check (anios_gestion >= 0), anios_central integer check (anios_central >= 0),
  disposicion text check (disposicion in ('conservar', 'eliminar', 'digitalizar')), tipos_sugeridos text not null default '',
  procedimiento text, acto_aprobacion text, activa integer not null default 1, creado_por integer references usuarios(id),
  fecha_creacion text not null default (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
  unique (empresa_id, codigo), unique (id, empresa_id),
  foreign key (serie_padre_id, empresa_id) references trd_series (id, empresa_id),
  check (serie_padre_id is null or (anios_gestion is not null and anios_central is not null and disposicion is not null)));
create table if not exists archivo_cajas (id integer primary key, empresa_id integer not null references empresas(id),
  codigo text not null, sede text not null, deposito text not null, estante text not null, entrepano text not null,
  capacidad_carpetas integer not null default 20 check (capacidad_carpetas > 0),
  estado text not null default 'abierta' check (estado in ('abierta', 'cerrada')), observaciones text,
  creado_por integer references usuarios(id), fecha_creacion text not null default (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
  unique (empresa_id, codigo), unique (id, empresa_id));
create table if not exists archivo_carpetas (id integer primary key, empresa_id integer not null references empresas(id),
  caja_id integer not null, numero integer not null check (numero > 0), codigo text not null, serie_id integer, anio integer,
  descripcion text, folio_inicial integer not null default 1, folio_final integer not null default 1,
  estado text not null default 'en_archivo' check (estado in ('en_archivo', 'prestada', 'dispuesta')), observaciones text,
  creado_por integer references usuarios(id), fecha_creacion text not null default (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
  unique (empresa_id, codigo), unique (caja_id, numero), unique (id, empresa_id),
  foreign key (caja_id, empresa_id) references archivo_cajas (id, empresa_id),
  foreign key (serie_id, empresa_id) references trd_series (id, empresa_id));
create table if not exists expedientes (id integer primary key, empresa_id integer not null references empresas(id),
  solicitud_id integer not null unique, serie_id integer not null, carpeta_id integer, fecha_cierre text not null,
  fecha_fin_gestion text not null, fecha_disposicion text not null,
  disposicion text not null check (disposicion in ('conservar', 'eliminar', 'digitalizar')), folios integer not null default 0,
  estado text not null default 'activo' check (estado in ('activo', 'con_propuesta', 'dispuesto')), resultado text, observacion text,
  asignado_por integer references usuarios(id), fecha_asignacion text not null default (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
  unique (id, empresa_id),
  foreign key (solicitud_id, empresa_id) references solicitudes (id, empresa_id),
  foreign key (serie_id, empresa_id) references trd_series (id, empresa_id),
  foreign key (carpeta_id, empresa_id) references archivo_carpetas (id, empresa_id));
create table if not exists expediente_docs (id integer primary key, empresa_id integer not null references empresas(id),
  expediente_id integer not null, orden integer not null, descripcion text not null,
  soporte text not null default 'electronico' check (soporte in ('electronico', 'fisico')), fecha_doc text,
  folios integer not null default 1, folio_inicial integer, folio_final integer, sha256 text,
  documento_id integer references documentos(id), unique (expediente_id, orden),
  foreign key (expediente_id, empresa_id) references expedientes (id, empresa_id));
create table if not exists trd_actas (id integer primary key, empresa_id integer not null references empresas(id),
  numero text not null, fecha text not null, aprobada_por integer references usuarios(id), contenido text not null,
  sha256 text not null, unique (empresa_id, numero), unique (id, empresa_id));
create table if not exists trd_disposiciones (id integer primary key, empresa_id integer not null references empresas(id),
  expediente_id integer not null, disposicion text not null check (disposicion in ('conservar', 'eliminar', 'digitalizar')),
  estado text not null default 'propuesta' check (estado in ('propuesta', 'revisada', 'rechazada', 'aprobada', 'ejecutada')),
  propuesta_en text not null, revisada_por integer references usuarios(id), revisada_en text, concepto_archivista text,
  aprobada_por integer references usuarios(id), aprobada_en text, observacion_aprobacion text, acta_id integer,
  ejecutada_por integer references usuarios(id), ejecutada_en text, detalle_ejecucion text,
  foreign key (expediente_id, empresa_id) references expedientes (id, empresa_id),
  foreign key (acta_id, empresa_id) references trd_actas (id, empresa_id));
create unique index if not exists uq_disposicion_abierta on trd_disposiciones (expediente_id)
  where estado in ('propuesta', 'revisada', 'aprobada');
create table if not exists archivo_prestamos (id integer primary key, empresa_id integer not null references empresas(id),
  carpeta_id integer not null, solicitante_id integer not null references usuarios(id), responsable_id integer references usuarios(id),
  motivo text, dias integer not null default 5 check (dias between 1 and 60), fecha_solicitud text not null,
  fecha_prestamo text, fecha_vence text, fecha_devolucion text, recibido_por integer references usuarios(id),
  estado text not null default 'solicitada' check (estado in ('solicitada', 'prestada', 'devuelta')), observaciones text,
  foreign key (carpeta_id, empresa_id) references archivo_carpetas (id, empresa_id));
create unique index if not exists uq_prestamo_activo on archivo_prestamos (carpeta_id) where estado = 'prestada';
create index if not exists ix_trd_series_empresa on trd_series (empresa_id);
create index if not exists ix_expedientes_empresa on expedientes (empresa_id, fecha_disposicion);
create index if not exists ix_expediente_docs_exp on expediente_docs (expediente_id);
create index if not exists ix_cajas_empresa on archivo_cajas (empresa_id);
create index if not exists ix_carpetas_empresa on archivo_carpetas (empresa_id, caja_id);
create index if not exists ix_prestamos_empresa on archivo_prestamos (empresa_id, estado);
create index if not exists ix_disposiciones_empresa on trd_disposiciones (empresa_id, estado);
