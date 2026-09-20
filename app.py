"""Interfaz web simple para generar los reportes por aerolinea.

Es solo una capa de UI: toda la logica de carga y filtrado sigue viviendo en
src/ (loader.py, report_builder.py, config.py) y no se modifica aca. Lo unico
que se reusa de mas es AIRLINE_CONFIGS/CHARGE_TYPES para poder agrupar el
resultado por tipo de cargo al mostrarlo, sin reimplementar el filtrado.

Ademas de generar el Excel como siempre, cada reporte generado se persiste en
Postgres via src/db.py (guardar_reporte_simple / guardar_liquidacion_latam) --
ver ese modulo para el detalle. Es un efecto secundario que nunca bloquea ni
cambia el Excel: si DATABASE_URL no esta configurada o la base falla, esas
funciones no hacen nada y el flujo de descarga sigue exactamente igual.

El estilo (paleta de azules extraida del logo, cards, tipografia, marca de
agua) se inyecta como CSS via st.markdown(unsafe_allow_html=True), ya que
Streamlit no permite theming tan especifico de forma nativa. Los selectores
CSS estan verificados contra el DOM real que genera Streamlit 1.58
(data-testid y la clase "st-key-<key>" que expone st.container(key=...)
para estilar contenedores puntuales). El logo (static/images/handyway-logo.png)
se embebe como data URI base64 -- no como archivo estatico servido por
separado -- para no depender de configuracion de static file serving en
Render.
"""

import base64
import io
import os

import streamlit as st

from src.config import AIRLINE_CONFIGS, CHARGE_TYPES, COL_COD_VUELO, FLOW_LIQUIDACION
from src.db import guardar_liquidacion_latam, guardar_reporte_simple
from src.liquidacion_builder import (
    build_latam_detalle,
    build_latam_resumen,
    detect_latam_period_exclusions,
    detect_unconfirmed_station_activity,
    write_liquidacion,
)
from src.loader import load_original
from src.period_utils import extract_period, period_label, period_slug
from src.report_builder import (
    build_airline_report,
    detect_period_exclusions,
    detect_unconfirmed_activity,
    write_report,
)

CHARGE_TYPE_LABELS = {
    "delivery_fee": ("📦", "Delivery Fee"),
    "trans_electronica": ("📡", "Transmisión Electrónica"),
    "collect": ("💰", "Collect"),
}

LOGO_PATH = os.path.join("static", "images", "handyway-logo.png")


def _logo_base64() -> str:
    """Lee el logo del disco y lo devuelve como data URI base64.

    Se embebe inline en el HTML (en vez de servirlo como archivo estatico)
    para no depender de que Render sirva la carpeta static/ -- funciona
    igual en cualquier hosting, sin configuracion adicional.
    """
    with open(LOGO_PATH, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


LOGO_DATA_URI = _logo_base64()

st.set_page_config(page_title="Reportes HWC", page_icon=LOGO_PATH, layout="centered")

# ---------------------------------------------------------------------------
# Estilo corporativo. Paleta extraida directamente del logo de Handyway
# Cargo (static/images/handyway-logo.png), no inventada: --hwc-blue-light y
# --hwc-blue son los dos tonos reales del icono (muestreados con Pillow),
# --hwc-blue-text es el tono del wordmark "Handyway Cargo", y --hwc-blue-deep
# / --hwc-blue-deepest son ese mismo matiz (H=204-205) oscurecido para tener
# un navy de marca para fondos oscuros -- mismo tono, no un azul generico.
# ---------------------------------------------------------------------------
st.markdown(
    f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {{
    --hwc-blue-deepest: #112E41;
    --hwc-blue-deep: #173F59;
    --hwc-blue: #2D79AB;
    --hwc-blue-light: #3895D1;
    --hwc-blue-text: #2C5877;
    --hwc-bg-1: #DDE7EE;
    --hwc-bg-2: #C9D8E3;
    --hwc-card: #FFFFFF;
    --hwc-text: #1F2933;
    --hwc-text-muted: #64748B;
    --hwc-border: #DCE7EE;
    --hwc-success: #1E8E5A;
}}

html, body, [data-testid="stApp"], [data-testid="stAppViewContainer"], [data-testid="stMain"] {{
    background: linear-gradient(160deg, var(--hwc-bg-1) 0%, var(--hwc-bg-2) 100%) !important;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    color: var(--hwc-text);
}}

/* Limpiar el chrome default de Streamlit (Deploy / menu) para look interno */
[data-testid="stToolbar"] {{ visibility: hidden; }}
[data-testid="stHeader"] {{ background: transparent; }}

/* --- Marca de agua: el logo, muy sutil, de fondo detras del contenido.
   Es un <div> real (ver hwc-watermark mas abajo en el markdown), no un
   ::before: en el DOM que genera Streamlit 1.58 el pseudo-elemento no
   llega a pintarse en este contenedor (probado en el navegador real -- el
   mismo data URI SI renderiza como elemento normal), asi que se opta por
   un div, que es la forma que efectivamente se ve. Vive en su propia caja
   (no hereda opacity de los hijos), asi que bajar su opacity no afecta el
   contenido real -- solo hace falta que el contenido tenga z-index por
   encima. Se ancla a una esquina (no al centro) a proposito: el layout es
   una columna centrada angosta (max-width 760px), asi que un watermark
   centrado queda tapado por las cards en cualquier ancho de pantalla; en
   una esquina asoma en el margen en desktop y se recorta parcialmente en
   mobile, sin competir nunca con el contenido. "fixed" (no "absolute")
   para que quede anclado a la esquina del viewport tambien mientras se
   scrollea una pagina larga (no hay ancestros con transform que rompan el
   containing block de fixed -- verificado). --- */
.hwc-watermark {{
    position: fixed;
    inset: 0;
    background-image: url('{LOGO_DATA_URI}');
    background-repeat: no-repeat;
    background-position: bottom -60px right -60px;
    background-size: 520px;
    opacity: 0.07;
    pointer-events: none;
    z-index: 0;
}}
[data-testid="stMainBlockContainer"] {{
    max-width: 760px;
    padding-top: 2.2rem;
    padding-bottom: 3rem;
    position: relative;
    z-index: 1;
}}

h1, h2, h3 {{ font-family: 'Inter', sans-serif; font-weight: 800; color: var(--hwc-blue-text); letter-spacing: -0.01em; }}
/* Nota: no pisar el color de todos los <p> de stMarkdownContainer aca:
   Streamlit tambien usa ese mismo contenedor para el texto de los botones,
   asi que una regla global de color rompe el texto blanco de los botones
   y del banner. El color de cuerpo normal ya se hereda de html/body. */
[data-testid="stCaptionContainer"] {{ color: var(--hwc-text-muted) !important; }}
[data-testid="stWidgetLabel"] p {{ font-weight: 600; color: var(--hwc-text); font-size: 0.85rem; }}

/* --- Titulo principal, con el logo al lado del nombre --- */
.hwc-page-title {{
    display: flex; align-items: center; gap: 0.85rem;
    font-size: 2.4rem; font-weight: 800; color: var(--hwc-blue-text);
    letter-spacing: -0.02em; line-height: 1.1;
    margin: 0 0 1.2rem 0;
}}
.hwc-page-title-logo {{ height: 3rem; width: auto; flex-shrink: 0; }}

/* --- Banner superior de marca --- */
.hwc-hero {{
    background: linear-gradient(135deg, var(--hwc-blue-deep) 0%, var(--hwc-blue) 100%);
    border-radius: 16px;
    padding: 1.8rem 2.1rem;
    margin-bottom: 1.6rem;
    box-shadow: 0 10px 30px -14px rgba(17, 46, 65, 0.55);
    position: relative;
    overflow: hidden;
}}
.hwc-hero::after {{
    content: "";
    position: absolute;
    right: -50px;
    top: -60px;
    width: 180px;
    height: 180px;
    background: rgba(255, 255, 255, 0.09);
    border-radius: 50%;
}}
.hwc-hero-sub {{ color: rgba(255, 255, 255, 0.82) !important; font-size: 0.85rem; margin: 0; position: relative; }}
.hwc-hero-tag {{
    display: inline-block; margin-top: 0.9rem;
    background: rgba(255, 255, 255, 0.14); border: 1px solid rgba(255, 255, 255, 0.35);
    color: #fff; font-size: 0.7rem; font-weight: 700; letter-spacing: 0.06em;
    text-transform: uppercase; padding: 0.28rem 0.75rem; border-radius: 100px; position: relative;
}}

/* --- Cards de seccion (subir archivo / aerolinea / resultado / login) --- */
.st-key-card_upload[data-testid="stVerticalBlock"],
.st-key-card_config[data-testid="stVerticalBlock"],
.st-key-card_result[data-testid="stVerticalBlock"],
.st-key-card_login[data-testid="stVerticalBlock"] {{
    background: var(--hwc-card);
    border: 1px solid var(--hwc-border);
    border-radius: 16px;
    padding: 1.7rem 1.8rem 1.5rem 1.8rem;
    box-shadow: 0 4px 22px -10px rgba(23, 63, 89, 0.14);
    margin-bottom: 1.3rem;
}}

.hwc-step {{
    display: flex; align-items: center; gap: 0.65rem;
    font-weight: 700; font-size: 1.05rem; color: var(--hwc-blue-text);
    margin-bottom: 1rem;
}}
.hwc-step-num {{
    display: inline-flex; align-items: center; justify-content: center;
    width: 27px; height: 27px; border-radius: 50%; flex-shrink: 0;
    background: linear-gradient(135deg, var(--hwc-blue-light) 0%, var(--hwc-blue) 100%);
    color: #fff; font-size: 0.85rem; font-weight: 800;
    box-shadow: 0 3px 8px -2px rgba(45, 121, 171, 0.55);
}}

/* --- Dropzone de archivos --- */
[data-testid="stFileUploaderDropzone"] {{
    background: #FAFBFD !important;
    border: 1.5px dashed var(--hwc-border) !important;
    border-radius: 10px !important;
}}

/* --- Select --- */
div[data-baseweb="select"] > div {{ border-radius: 8px !important; }}

/* --- Botones primarios (Generar reporte) --- */
[data-testid="stBaseButton-primary"] {{
    background: linear-gradient(135deg, var(--hwc-blue-deep) 0%, var(--hwc-blue) 100%) !important;
    color: #fff !important;
    border: none !important;
    border-radius: 9px !important;
    font-weight: 600 !important;
    padding: 0.6rem 1.6rem !important;
    box-shadow: 0 4px 14px -4px rgba(23, 63, 89, 0.45);
    transition: filter .15s ease, box-shadow .15s ease, transform .05s ease;
}}
[data-testid="stBaseButton-primary"]:hover {{
    filter: brightness(1.12);
    box-shadow: 0 6px 18px -4px rgba(23, 63, 89, 0.6);
}}
[data-testid="stBaseButton-primary"]:active {{ transform: translateY(1px); }}
[data-testid="stBaseButton-primary"] p {{ color: #fff !important; font-weight: 600 !important; }}
[data-testid="stBaseButton-primary"]:disabled {{
    background: #C7D2DA !important;
    color: #8A96A3 !important;
    box-shadow: none;
}}
[data-testid="stBaseButton-primary"]:disabled p {{ color: #8A96A3 !important; }}
[data-testid="stBaseButton-secondary"] {{
    border-radius: 9px !important;
    border: 1.5px solid var(--hwc-blue) !important;
    color: var(--hwc-blue-text) !important;
    font-weight: 600 !important;
    transition: background-color .15s ease;
}}
[data-testid="stBaseButton-secondary"] p {{ color: var(--hwc-blue-text) !important; font-weight: 600 !important; }}
[data-testid="stBaseButton-secondary"]:hover {{ background: var(--hwc-bg-1) !important; }}

/* El boton de descarga vive dentro del card de resultado: lo diferenciamos
   con el azul claro de acento (accion final) vs. el azul profundo de
   "Generar reporte". */
.st-key-card_result [data-testid="stBaseButton-primary"] {{
    background: linear-gradient(135deg, var(--hwc-blue-light) 0%, var(--hwc-blue) 100%) !important;
    box-shadow: 0 4px 14px -4px rgba(56, 149, 209, 0.55);
}}

[data-testid="stAlert"] {{ border-radius: 12px; font-size: 0.85rem; padding: 0.85rem 1rem; }}

/* --- Mini-cards por tipo de cargo dentro del resultado --- */
.hwc-group-card {{
    background: #FAFBFD;
    border: 1px solid var(--hwc-border);
    border-radius: 12px;
    padding: 1rem 1.15rem;
    margin-bottom: 0.9rem;
}}
.hwc-group-title {{
    font-weight: 700; color: var(--hwc-blue-text); font-size: 0.95rem;
    margin-bottom: 0.55rem; display: flex; align-items: center; gap: 0.4rem;
}}
.hwc-row {{ display: flex; align-items: center; gap: 0.55rem; font-size: 0.86rem; padding: 0.24rem 0; }}
.hwc-dot {{
    display: inline-flex; align-items: center; justify-content: center;
    width: 18px; height: 18px; border-radius: 50%; font-size: 0.65rem;
    font-weight: 800; flex-shrink: 0;
}}
.hwc-dot-active {{ background: var(--hwc-success); color: #fff; }}
.hwc-dot-empty {{ background: #E4E9F0; color: #9AA5B1; }}
.hwc-row-active {{ color: var(--hwc-text); }}
.hwc-row-empty {{ color: var(--hwc-text-muted); }}
.hwc-count {{
    margin-left: auto; font-weight: 700; color: var(--hwc-blue-text);
    background: #EAF1F6; padding: 0.15rem 0.65rem; border-radius: 100px; font-size: 0.78rem;
}}

/* --- Pantalla de acceso --- */
.hwc-login-wrap {{ display: flex; flex-direction: column; align-items: center; text-align: center; }}
.hwc-login-logo {{ height: 4.5rem; width: auto; margin-bottom: 1.1rem; }}
.hwc-login-title {{ font-size: 1.3rem; font-weight: 700; color: var(--hwc-blue-text); margin-bottom: 0.3rem; }}
.hwc-login-sub {{ color: var(--hwc-text-muted); font-size: 0.85rem; margin-bottom: 1.4rem; }}
.st-key-card_login [data-testid="stTextInput"] input {{
    border-radius: 9px !important;
    text-align: center;
}}

/* --- Footer --- */
.hwc-footer {{
    text-align: center; color: var(--hwc-text-muted); font-size: 0.78rem;
    margin-top: 1.6rem; padding-top: 1rem; border-top: 1px solid var(--hwc-border);
}}

/* --- Responsive: pantallas chicas --- */
@media (max-width: 480px) {{
    [data-testid="stMainBlockContainer"] {{ padding-left: 1rem !important; padding-right: 1rem !important; }}
    .hwc-page-title {{ font-size: 1.7rem; gap: 0.55rem; }}
    .hwc-page-title-logo {{ height: 2.2rem; }}
    .hwc-hero {{ padding: 1.4rem 1.3rem; }}
    .st-key-card_upload[data-testid="stVerticalBlock"],
    .st-key-card_config[data-testid="stVerticalBlock"],
    .st-key-card_result[data-testid="stVerticalBlock"],
    .st-key-card_login[data-testid="stVerticalBlock"] {{ padding: 1.2rem 1.15rem; }}
    .hwc-watermark {{ background-size: 320px; background-position: bottom -30px right -30px; }}
}}
</style>
<div class="hwc-watermark"></div>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Acceso restringido (opcional): compara contra APP_PASSWORD, una variable
# de entorno configurada en Render (Settings > Environment) -- nunca
# hardcodeada en el codigo. Si no esta configurada (ej. en local), no
# bloquea a nadie. Es una traba basica para que el link no quede abierto a
# cualquiera, no un sistema de login: no hay sesion persistente entre
# pestañas o refrescos de pagina (st.session_state vive en esa conexion).
# ---------------------------------------------------------------------------
APP_PASSWORD = os.environ.get("APP_PASSWORD")


def _check_password() -> bool:
    if not APP_PASSWORD:
        return True
    if st.session_state.get("hwc_authenticated"):
        return True

    with st.container(border=True, key="card_login"):
        st.markdown(
            f"""
            <div class="hwc-login-wrap">
                <img class="hwc-login-logo" src="{LOGO_DATA_URI}" alt="Handyway Cargo" />
                <div class="hwc-login-title">🔒 Acceso restringido</div>
                <div class="hwc-login-sub">Ingresá la contraseña para ver los reportes de Handyway Cargo.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        password = st.text_input(
            "Contraseña", type="password", label_visibility="collapsed", placeholder="Contraseña"
        )
        if password:
            if password == APP_PASSWORD:
                st.session_state["hwc_authenticated"] = True
                st.rerun()
            else:
                st.error("Contraseña incorrecta.", icon="🚫")
    return False


if not _check_password():
    st.stop()

# ---------------------------------------------------------------------------
# Titulo principal (jerarquia por encima del banner de marca, sin tocarlo)
# ---------------------------------------------------------------------------
st.markdown(
    f'<div class="hwc-page-title"><img class="hwc-page-title-logo" src="{LOGO_DATA_URI}" alt="Handyway Cargo" />Handyway Cargo</div>',
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Banner de marca
# ---------------------------------------------------------------------------
st.markdown(
    """
<div class="hwc-hero">
    <p class="hwc-hero-sub">Generá reportes automáticos por aerolínea a partir del archivo original de Handyway Cargo.</p>
    <span class="hwc-hero-tag">Automatización de reportes</span>
</div>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Seccion 1: subir archivo
# ---------------------------------------------------------------------------
with st.container(border=True, key="card_upload"):
    st.markdown('<div class="hwc-step"><span class="hwc-step-num">1</span>📄 Subí el archivo</div>', unsafe_allow_html=True)
    uploaded_file = st.file_uploader("Archivo original (export del sistema)", type="xlsx", label_visibility="collapsed")

# ---------------------------------------------------------------------------
# Seccion 2: elegir aerolinea + generar
# ---------------------------------------------------------------------------
with st.container(border=True, key="card_config"):
    st.markdown('<div class="hwc-step"><span class="hwc-step-num">2</span>✈️ Elegí la aerolínea</div>', unsafe_allow_html=True)
    airline_key = st.selectbox("Aerolínea", options=sorted(AIRLINE_CONFIGS), format_func=str.upper, label_visibility="collapsed")
    generate = st.button("Generar reporte", disabled=uploaded_file is None, type="primary")


def _sheets_for_charge_type(sheets: dict, charge_type_key: str) -> dict:
    """Agrupa las hojas ya generadas segun a que tipo de cargo pertenecen.

    Es una funcion puramente de presentacion: usa la misma config de src/
    para saber que prefijo/nombre de hoja corresponde a cada tipo de cargo,
    pero no vuelve a filtrar ni calcular nada.
    """
    charge_cfg = CHARGE_TYPES[charge_type_key]
    if charge_cfg.get("per_station"):
        prefix = charge_cfg["sheet_prefix"] + " "
        return {name: d for name, d in sheets.items() if name.startswith(prefix)}
    name = charge_cfg["sheet_name"]
    return {name: sheets[name]} if name in sheets else {}


def _money(value: float) -> str:
    return f"$ {value:,.2f}"


def _render_liquidacion_result(uploaded_file) -> tuple[object, dict, tuple[str, str]]:
    """Corre el flujo de liquidacion de LATAM y muestra su propio resumen.

    A diferencia del reporte simple (conteo de filas por hoja), acá lo que
    importa mostrar son los totales del Resumen Facturación.
    """
    with st.spinner("Generando liquidación..."):
        df = load_original(uploaded_file)
        period, excluded = detect_latam_period_exclusions(df)
        detalle = build_latam_detalle(df, period=period)
        resumen = build_latam_resumen(detalle)

        buffer = io.BytesIO()
        write_liquidacion(detalle, resumen, buffer)
        buffer.seek(0)

        guardar_liquidacion_latam(
            nombre_archivo=uploaded_file.name,
            file_bytes=uploaded_file.getvalue(),
            df=df,
            period=period,
            detalle=detalle,
            resumen=resumen,
        )

    st.success("Liquidación generada correctamente.", icon="✅")
    st.caption(f"Período detectado: {period_label(period)}")

    if not excluded.empty:
        breakdown = excluded[COL_COD_VUELO].map(extract_period).value_counts()
        detalle_txt = ", ".join(f"{n} de {period_label(p)}" for p, n in breakdown.items())
        fila_word = "fila" if len(excluded) == 1 else "filas"
        st.warning(
            f"Se excluyeron {len(excluded)} {fila_word} fuera del período detectado "
            f"({period_label(period)}) de LATAM: {detalle_txt}.",
            icon="⚠️",
        )

    unconfirmed_stations = AIRLINE_CONFIGS["latam"].get("unconfirmed_stations", [])
    if unconfirmed_stations:
        activity = detect_unconfirmed_station_activity(df, unconfirmed_stations, period=period)
        if activity:
            detalle_txt = ", ".join(f"{station} ({_money(info['total'])})" for station, info in activity.items())
            st.warning(
                f"Se detectaron movimientos de LATAM sin incluir en esta liquidación "
                f"(estación no validada todavía): {detalle_txt}. Ese monto queda fuera de "
                f"TOTAL PERIODO — no se está facturando.",
                icon="⚠️",
            )

    st.markdown(
        f'<div class="hwc-group-card">'
        f'<div class="hwc-group-title">📑 Detalle de Facturación</div>'
        f'<div class="hwc-row hwc-row-active"><span class="hwc-dot hwc-dot-active">✓</span>'
        f'Guías con cargo (EZE)<span class="hwc-count">{len(detalle)} filas</span></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        f'<div class="hwc-group-card">'
        f'<div class="hwc-group-title">🧾 Resumen Facturación</div>'
        f'<div class="hwc-row hwc-row-active"><span class="hwc-dot hwc-dot-active">✓</span>'
        f'TOTAL LA (sin IVA)<span class="hwc-count">{_money(resumen["total_la"])}</span></div>'
        f'<div class="hwc-row hwc-row-active"><span class="hwc-dot hwc-dot-active">✓</span>'
        f'TOTAL 4M (con IVA)<span class="hwc-count">{_money(resumen["total_4m"])}</span></div>'
        f'<div class="hwc-row hwc-row-active"><span class="hwc-dot hwc-dot-active">✓</span>'
        f'TOTAL PERIODO<span class="hwc-count">{_money(resumen["total_periodo"])}</span></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        f'<div class="hwc-group-card">'
        f'<div class="hwc-group-title">📝 Compensación</div>'
        f'<div class="hwc-row hwc-row-empty"><span class="hwc-dot hwc-dot-empty">–</span>'
        f'pendiente de carga manual para este período</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    return buffer, resumen, period


# ---------------------------------------------------------------------------
# Seccion 3: resultado
# ---------------------------------------------------------------------------
if generate:
    with st.container(border=True, key="card_result"):
        st.markdown('<div class="hwc-step"><span class="hwc-step-num">3</span>📊 Resultado</div>', unsafe_allow_html=True)

        airline_cfg = AIRLINE_CONFIGS[airline_key]

        if airline_cfg.get("flow") == FLOW_LIQUIDACION:
            buffer, _, period = _render_liquidacion_result(uploaded_file)
        else:
            with st.spinner("Generando reporte..."):
                df = load_original(uploaded_file)
                period, excluded = detect_period_exclusions(df, airline_key)
                sheets = build_airline_report(df, airline_key, period=period)

                buffer = io.BytesIO()
                write_report(sheets, buffer)
                buffer.seek(0)

                guardar_reporte_simple(
                    nombre_archivo=uploaded_file.name,
                    file_bytes=uploaded_file.getvalue(),
                    df=df,
                    airline_key=airline_key,
                    period=period,
                    sheets=sheets,
                )

            st.success("Reporte generado correctamente.", icon="✅")
            st.caption(f"Período detectado: {period_label(period)}")

            if not excluded.empty:
                breakdown = excluded[COL_COD_VUELO].map(extract_period).value_counts()
                detalle_txt = ", ".join(f"{n} de {period_label(p)}" for p, n in breakdown.items())
                fila_word = "fila" if len(excluded) == 1 else "filas"
                st.warning(
                    f"Se excluyeron {len(excluded)} {fila_word} fuera del período detectado "
                    f"({period_label(period)}) del reporte de {airline_key.upper()}: {detalle_txt}.",
                    icon="⚠️",
                )

            unconfirmed_stations = airline_cfg.get("unconfirmed_stations", [])
            if unconfirmed_stations:
                activity = detect_unconfirmed_activity(sheets, unconfirmed_stations)
                if activity:
                    estaciones = ", ".join(activity)
                    st.warning(
                        f"Se detectaron movimientos en {estaciones} para {airline_key.upper()}. "
                        f"La tarifa aplicada ahí todavía no está confirmada con el cliente — "
                        f"revisá los montos manualmente antes de usarlos.",
                        icon="⚠️",
                    )

            for charge_type_key in airline_cfg["charge_types"]:
                icon, label = CHARGE_TYPE_LABELS.get(charge_type_key, ("📁", charge_type_key))
                group_sheets = _sheets_for_charge_type(sheets, charge_type_key)

                rows_html = ""
                for sheet_name, sheet_df in group_sheets.items():
                    n_rows = len(sheet_df)
                    if n_rows == 0:
                        rows_html += (
                            f'<div class="hwc-row hwc-row-empty">'
                            f'<span class="hwc-dot hwc-dot-empty">–</span>{sheet_name} · sin movimiento</div>'
                        )
                    else:
                        rows_html += (
                            f'<div class="hwc-row hwc-row-active">'
                            f'<span class="hwc-dot hwc-dot-active">✓</span>{sheet_name}'
                            f'<span class="hwc-count">{n_rows} filas</span></div>'
                        )

                st.markdown(
                    f'<div class="hwc-group-card">'
                    f'<div class="hwc-group-title">{icon} {label}</div>'
                    f'{rows_html}</div>',
                    unsafe_allow_html=True,
                )

        st.download_button(
            label="⬇️ Descargar reporte",
            data=buffer,
            file_name=f"{airline_key}_{period_slug(period)}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )

st.markdown('<div class="hwc-footer">Handyway Cargo · Automatización de reportes</div>', unsafe_allow_html=True)
