-- Etapa 1 de persistencia: historial de cargas/movimientos/liquidaciones +
-- tarifas editables. No reemplaza ningun calculo existente (ver README /
-- src/db.py): esto es una capa aditiva por debajo de la app ya validada.

-- Representa UN archivo subido, identificado por el hash de su contenido
-- (no por aerolinea ni por cuando se uso): el mismo archivo puede generar
-- reportes de Avianca, Gol y LATAM sin volver a subirse, y no queremos
-- triplicar movimientos_awb cada vez que eso pasa.
CREATE TABLE cargas_archivo (
    id                       BIGSERIAL PRIMARY KEY,
    nombre_archivo           TEXT NOT NULL,
    archivo_hash             CHAR(64) NOT NULL UNIQUE,
    periodo_mes              TEXT NOT NULL,
    periodo_anio             TEXT NOT NULL,
    periodo                  DATE NOT NULL,
    filas_totales            INTEGER NOT NULL,
    filas_excluidas_periodo  INTEGER NOT NULL DEFAULT 0,
    subido_en                TIMESTAMPTZ NOT NULL DEFAULT now(),
    subido_por               TEXT
);
CREATE INDEX idx_cargas_archivo_periodo ON cargas_archivo(periodo);
CREATE INDEX idx_cargas_archivo_subido_en ON cargas_archivo(subido_en);

-- Cada fila (movimiento) del archivo original.xlsx, de TODAS las
-- aerolineas presentes en esa carga, no solo la que se reporto ese dia.
-- Las 13 columnas cubren el archivo real completo (ver data/archivo
-- original.xlsx): no hay peso/kg en la fuente hoy -- ver nota en el
-- mensaje de aprobacion del schema.
CREATE TABLE movimientos_awb (
    id          BIGSERIAL PRIMARY KEY,
    carga_id    BIGINT NOT NULL REFERENCES cargas_archivo(id) ON DELETE CASCADE,
    codigo      TEXT,
    cod_vuelo   TEXT,
    cliente     TEXT,
    condicion   TEXT,
    tipo        TEXT,
    tpo_cambio  NUMERIC(12,4),
    dry_fee     NUMERIC(14,2),
    aduana      NUMERIC(14,2),
    trans_e     NUMERIC(14,2),
    iata        NUMERIC(14,2),
    collect     NUMERIC(14,2),
    aerolinea   TEXT NOT NULL,
    estacion    TEXT,
    creado_en   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_movimientos_awb_carga ON movimientos_awb(carga_id);
CREATE INDEX idx_movimientos_awb_aerolinea_estacion ON movimientos_awb(aerolinea, estacion);
CREATE INDEX idx_movimientos_awb_cod_vuelo ON movimientos_awb(cod_vuelo);

-- Una fila por hoja/total generado (estacion + tipo de cargo), asi se
-- puede filtrar por estacion individual despues. Para LATAM (liquidacion
-- formal, no por estacion/hoja) tipo_cargo='latam_liquidacion' y
-- detalle_totales guarda el desglose completo (total_la, neto_gravado,
-- iva, total_4m, total_periodo, sums).
CREATE TABLE liquidaciones (
    id              BIGSERIAL PRIMARY KEY,
    carga_id        BIGINT NOT NULL REFERENCES cargas_archivo(id) ON DELETE CASCADE,
    aerolinea       TEXT NOT NULL,
    estacion        TEXT NOT NULL,
    tipo_cargo      TEXT NOT NULL,
    periodo_mes     TEXT NOT NULL,
    periodo_anio    TEXT NOT NULL,
    periodo         DATE NOT NULL,
    cantidad_filas  INTEGER NOT NULL,
    monto_total     NUMERIC(14,2),
    detalle_totales JSONB,
    generado_en     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_liquidaciones_aerolinea_periodo ON liquidaciones(aerolinea, periodo);
CREATE INDEX idx_liquidaciones_carga ON liquidaciones(carga_id);

-- Compensaciones/correcciones manuales ligadas a una liquidacion puntual.
-- Se crea en esta etapa SIN UI para cargarla todavia (ver alcance).
CREATE TABLE ajustes_manuales (
    id             BIGSERIAL PRIMARY KEY,
    liquidacion_id BIGINT NOT NULL REFERENCES liquidaciones(id) ON DELETE CASCADE,
    monto_ajuste   NUMERIC(14,2) NOT NULL,
    motivo         TEXT NOT NULL,
    ajustado_por   TEXT NOT NULL,
    creado_en      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_ajustes_manuales_liquidacion ON ajustes_manuales(liquidacion_id);

-- Tarifas por aerolinea/estacion/tipo de cargo, editable sin tocar
-- codigo. Se crea y se siembra en esta etapa, pero el calculo SIGUE
-- leyendo de src/config.py como hasta ahora (ver alcance): esta tabla
-- todavia no esta conectada a report_builder.py.
CREATE TABLE tarifas (
    id             BIGSERIAL PRIMARY KEY,
    aerolinea      TEXT NOT NULL,
    estacion       TEXT NOT NULL,
    tipo_cargo     TEXT NOT NULL,
    moneda         TEXT NOT NULL DEFAULT 'USD',
    monto          NUMERIC(14,4) NOT NULL,
    vigente_desde  DATE NOT NULL DEFAULT CURRENT_DATE,
    vigente_hasta  DATE,
    confirmado     BOOLEAN NOT NULL DEFAULT FALSE,
    notas          TEXT,
    creado_en      TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_tarifas_lookup ON tarifas(aerolinea, estacion, tipo_cargo, vigente_desde);

INSERT INTO tarifas (aerolinea, estacion, tipo_cargo, moneda, monto, confirmado, notas)
VALUES ('avianca', 'EZE', 'delivery_fee', 'USD', 200, TRUE, 'Confirmado por Cristian Nagel — margen fijo Handyway');
