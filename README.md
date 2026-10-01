# HWC Automatizaciones

Automatiza el armado de los reportes por aerolínea que Handyway Cargo hoy arma
a mano a partir del export completo del sistema (`archivo original.xlsx`).

## Cómo correr el script

```
python -m src.main --airline avianca
python -m src.main --airline gol
```

Esto lee `data/archivo original.xlsx` y genera `output/<airline>.xlsx` con una
hoja por combinación de tipo de cargo y estación.

Parámetros opcionales:

```
python -m src.main --airline gol --input "data/archivo original.xlsx" --output "output/gol.xlsx"
```

- `--airline`: obligatorio. Aerolíneas disponibles hoy: `avianca`, `gol`, `latam`, `jetsmart`.
- `--input`: ruta al export del sistema (default: `data/archivo original.xlsx`).
- `--output`: ruta del archivo a generar (default: `output/<airline>.xlsx`).

## Qué hace cada archivo de `src/`

- **`config.py`** — toda la configuración que depende de la aerolínea o del
  tipo de cargo: qué tipos de cargo se le facturan a cada aerolínea, qué
  columnas lleva cada tipo de cargo en el reporte final, y la lista de
  estaciones canónicas. Agregar una aerolínea nueva o un tipo de cargo nuevo
  es sumar una entrada acá, sin tocar el resto del código.
- **`loader.py`** — carga `archivo original.xlsx` y lo deja limpio: descarta
  la columna vacía del export y la fila de totales del pie de la planilla.
- **`report_builder.py`** — la lógica de filtrado y armado de hojas. Filtra
  por aerolínea y por estación, selecciona las columnas del tipo de cargo
  correspondiente, y arma una hoja por combinación (o agrupada, para
  Collect). No hace ningún cálculo de tarifas ni de IVA.
- **`main.py`** — el CLI: conecta `loader` y `report_builder` y escribe el
  archivo final.
- **`config_tarifas.py`** — placeholder vacío para la segunda etapa
  (cálculo de tarifas/IVA). Todavía no tiene lógica implementada.

## Supuestos tomados

- **Hojas sin movimiento**: si una combinación de tipo de cargo y estación no
  tiene ninguna fila para esa aerolínea, se genera igual la hoja con una
  única celda de texto ("Sin movimiento de awbs de importación destino
  {estación}"), replicando el criterio que ya usa Gol en su reporte manual.
- **Tipos de cargo por aerolínea**: qué tipos de cargo se facturan a cada
  aerolínea es una decisión de negocio, no algo que se pueda inferir de los
  datos. Por ejemplo, Gol tiene filas con `Trans.E.` distinto de cero en el
  archivo original, pero ese cargo no se le reporta (se gestiona por otra
  vía). Hoy están confirmados:
  - Avianca: Delivery Fee + Transmisión Electrónica.
  - Gol: Delivery Fee + Collect.
- **Estaciones**: por defecto se genera una hoja por cada combinación de
  tipo de cargo y estación en EZE, COR, ROS, MDZ y AEP. NQN queda afuera de
  la lista canónica porque en el archivo original solo aparece con
  movimientos de LATAM.
  - **Excepción confirmada para Avianca** (Cristian, 17/9/2026): Delivery
    Fee solo se factura en EZE y COR, y Transmisión Electrónica solo en
    EZE. No es una tarifa sin confirmar: esas combinaciones de
    estación/tipo de cargo directamente no existen para Avianca, así que
    no se genera hoja (ni vacía) para las estaciones que quedan afuera,
    aunque el archivo original traiga filas ahí. Ver
    `AVIANCA_DELIVERY_FEE_STATIONS` / `AVIANCA_TRANS_ELECTRONICA_STATIONS`
    en `src/config.py`.
- **Sin cálculos derivados**: en esta etapa las columnas de monto (`Dry.Fee`,
  `Trans.E.`, `Iata`, `Collect`) se copian tal cual vienen del original, sin
  ningún split ni conversión (por ejemplo, no se hace el split USD/ARS que
  el reporte manual de Avianca tiene en su hoja "Delivery Fee EZE").

## JetSmart

JetSmart tiene su propio flujo (`src/jetsmart_builder.py`), porque no parte de
`archivo original.xlsx` sino del export del sistema de guías filtrado por
Empresa (`# Guía`, `KGs`, `$ Prioridad`, …), y su liquidación no se parece a la
de LATAM. Genera las hojas GUIAS, LIQUIDACION, CVLP y COMISIONES INTER:

- **Ventas Netas**: suma de `$ Prioridad`. Ventas totales = netas + IVA 21%.
- **Comisión doméstica**: 7,5% de Ventas Netas.
- **Comisión internacional**: vuelos × USD por vuelo (EZE 17,5, MDZ 35) × TC.
- **GHA Services**: Kg por estación de origen × tarifa USD/kg × TC.
- **IVA de servicios e IIBB**: 0, igual que en la planilla de julio 2026.

```
python -m src.main --airline jetsmart --input export_guias.xlsx --tc 1485 --vuelos EZE=56 MDZ=38
```

Datos manuales: el **tipo de cambio** y la **cantidad de vuelos
internacionales** (salen de los manifiestos) no vienen en ningún export. Se
cargan al generar la liquidación, en la app o por CLI.

Fuera de alcance: el cruce contra el archivo de Ariel (JetSmart) y la
validación contra AFIP. Por eso la liquidación toma todas las guías del export
tal cual vienen, y la app lo avisa. En julio 2026 eso da +$525.640 de Ventas
Netas contra la liquidación armada a mano (36 guías del export que el cruce
dejó afuera y 24 que agregó).

Regresión: `python -m unittest tests.test_jetsmart_regresion -v`. Necesita los
archivos reales en `tests/fixtures/jetsmart/`, que no se versionan. Compara
celda por celda las hojas LIQUIDACION y CVLP contra `LIQ_ECS_07-2026_00000005.xlsx`.

## Pendiente de confirmar con el cliente

- **Tipo de cambio de JetSmart**: sin confirmar de dónde sale; por ahora se
  carga a mano. (La tarifa GHA de 0,185 USD/kg quedó confirmada como fija por
  Anita el 1/10/2026 para todas las estaciones de JetSmart; ver
  `JETSMART_TARIFA_CONFIRMADA_STATIONS` en `src/config.py`.)
- **Tarifas e IVA**: toda la lógica de cálculo de tarifas (incluyendo el
  split USD/ARS de Delivery Fee) y de IVA queda para una segunda etapa,
  porque depende de una tabla de tarifas que todavía no está confirmada.
  `src/config_tarifas.py` es el lugar reservado para esa lógica.
- **Alcance de LATAM**: no hay un reporte de referencia armado a mano para
  LATAM (sí para Avianca y Gol), así que no está confirmado qué tipos de
  cargo se le facturan. Hay una entrada de ejemplo comentada en
  `config.py` (`AIRLINE_CONFIGS`) lista para descomentar y ajustar una vez
  que el cliente lo confirme.

## Nota sobre la promoción a producción (2026-09-16)

Este proyecto se promovió al repo de producción (`holdingmax/hwc-reportes`)
en el commit `3fd52bb` con 3 preguntas de tarifas todavía sin confirmar por
el cliente:

- Tarifas de estación para Avianca en ROS, MDZ y AEP.
- Tarifas de estación para LATAM en COR, ROS, MDZ y NQN.
- Criterio de hojas vacías en Avianca.

Se le consultó al cliente 3 veces sobre estos puntos sin recibir respuesta.
La app ya muestra avisos (banners) visibles para las estaciones sin
confirmar, así que se decidió promover igual mientras se espera la
confirmación, en lugar de bloquear el lanzamiento.

**Actualización (17/9/2026)**: Cristian confirmó que el punto de Avianca
ROS/MDZ/AEP no era una tarifa pendiente de confirmar, sino una regla de
negocio real: Avianca no factura Delivery Fee en ROS, MDZ ni AEP, ni
Transmisión Electrónica fuera de EZE (ver "Excepción confirmada para
Avianca" más arriba). Con eso resuelto, la única tarifa real pendiente de
confirmación es la de LATAM en COR, ROS, MDZ y NQN — el cliente aprobó que
mientras tanto se siga usando el comportamiento actual (dato bruto sin
ajuste) como válido. El criterio de hojas vacías en Avianca sigue sin
confirmar. Gol y LATAM (fuera de esa tarifa) quedaron confirmados OK tal
como están.
