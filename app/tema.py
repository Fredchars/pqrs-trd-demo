"""Tema visual y componentes de interfaz (tarjetas, indicadores, insignias, estados vacíos y pie de página).

Paleta: azul marino (confianza), turquesa (acción) y semáforo (verde/amarillo/rojo). Pensada para pantalla de portátil y
proyector: texto grande, buen contraste y sin depender solo del color (cada insignia lleva texto o ícono)."""
from __future__ import annotations

import html

import streamlit as st

PIE_TEXTO = "Powered by ATm Consulting"

CSS = """
<style>
:root { --azul:#12355B; --azul2:#1E5AA8; --teal:#0EA5A4; --teal-claro:#5EEAD4; --fondo:#F5F7FB; --texto:#0F172A;
        --borde:#E2E8F0; --suave:#64748B; --radio:14px; --sombra:0 2px 10px rgba(18,53,91,.08); }
html, body, [class*="css"] { font-family: "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif; font-size:16px; }
.stApp { background: var(--fondo); }
/* Contenido principal: aire y espacio para el pie de página fijo */
[data-testid="stMainBlockContainer"], .block-container { padding-top: 1.4rem !important; padding-bottom: 4.6rem !important; max-width: 1280px; }
/* Títulos: barra de acento a la izquierda */
h1 { color: var(--azul) !important; font-weight: 800 !important; letter-spacing: -.01em; border-left: 7px solid var(--teal);
     padding-left: .75rem !important; margin-bottom: .6rem !important; }
h2, h3 { color: var(--azul) !important; font-weight: 700 !important; }
/* Botones y controles */
.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button {
  border-radius: 10px; font-weight: 600; border: 1px solid #CBD5E1; padding: .45rem 1rem; transition: all .15s ease; }
.stButton > button:hover, .stDownloadButton > button:hover { border-color: var(--azul2); box-shadow: 0 2px 8px rgba(30,90,168,.25); transform: translateY(-1px); }
.stButton > button[kind="primary"], [data-testid="stFormSubmitButton"] > button[kind="primary"] {
  background: linear-gradient(135deg, var(--azul2), var(--azul)); color: #fff; border: 0; }
.stButton > button[kind="primary"]:hover { filter: brightness(1.1); }
[data-testid="stMetric"] { background:#fff; border:1px solid var(--borde); border-radius: var(--radio); padding:.8rem 1rem; box-shadow: var(--sombra); }
[data-testid="stMetricValue"] { font-size:1.35rem; line-height:1.25; }
[data-testid="stMetricValue"], [data-testid="stMetricValue"] * { white-space:normal !important; overflow:visible !important; text-overflow:clip !important; word-break:break-word; }
[data-testid="stExpander"] { border-radius: 12px; border:1px solid var(--borde); background:#fff; }
div[data-testid="stVerticalBlockBorderWrapper"] { border-radius: var(--radio); }
.stTabs [data-baseweb="tab-list"] { gap:.3rem; border-bottom:2px solid var(--borde); }
.stTabs [data-baseweb="tab"] { font-weight:600; padding:.55rem 1rem; border-radius:10px 10px 0 0; }
.stTabs [aria-selected="true"] { background:#fff; color: var(--azul2); }
[data-testid="stDataFrame"] { border:1px solid var(--borde); border-radius:12px; overflow:hidden; box-shadow: var(--sombra); }
/* Barra lateral */
[data-testid="stSidebar"] { border-right: 3px solid var(--teal); }
[data-testid="stSidebarNav"] ul li a, [data-testid="stSidebar"] a[data-testid="stSidebarNavLink"] { border-radius: 10px; font-weight: 600; margin: 1px 0; }
[data-testid="stSidebarNavSeparator"], [data-testid="stSidebarNav"] [data-testid="stNavSectionHeader"], [data-testid="stSidebarNav"] header {
  text-transform: uppercase; letter-spacing: .08em; font-size: .72rem !important; opacity: .85; font-weight: 800; }
/* Aviso beta compacto */
.beta-banner { background: linear-gradient(90deg,#7F1D1D,#B91C1C); color:#fff; padding:.4rem .9rem; border-radius:10px; font-weight:700;
               margin-bottom:.8rem; font-size:.9rem; box-shadow: var(--sombra); }
.beta-banner small { font-weight:400; opacity:.95; }
/* Cabecera de página (hero) */
.hero { background: linear-gradient(120deg, var(--azul) 0%, var(--azul2) 60%, var(--teal) 130%); color:#fff; border-radius:18px;
        padding:1.3rem 1.6rem; margin:.2rem 0 1rem 0; box-shadow: 0 6px 22px rgba(18,53,91,.25); display:flex; gap:1rem; align-items:center; }
.hero .ico { font-size:2.6rem; background:rgba(255,255,255,.16); width:70px; height:70px; border-radius:18px; display:flex;
             align-items:center; justify-content:center; flex:0 0 auto; }
.hero h2 { color:#fff !important; margin:0 0 .15rem 0; font-size:1.65rem; padding:0; border:0; }
.hero p { margin:0; opacity:.93; font-size:1.02rem; }
.hero .chips { margin-top:.5rem; display:flex; flex-wrap:wrap; gap:.4rem; }
.chip { background:rgba(255,255,255,.18); border:1px solid rgba(255,255,255,.35); padding:.12rem .65rem; border-radius:999px; font-size:.85rem; font-weight:600; }
/* Indicadores */
.kpi-grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap:.8rem; margin:.3rem 0 1rem 0; }
.kpi { background:#fff; border:1px solid var(--borde); border-radius: var(--radio); padding:.9rem 1rem; display:flex; gap:.8rem; align-items:center;
       box-shadow: var(--sombra); border-left:6px solid var(--azul2); }
.kpi .kico { font-size:1.7rem; width:46px; height:46px; border-radius:12px; display:flex; align-items:center; justify-content:center; background:#EAF0F8; flex:0 0 auto; }
.kpi .kval { font-size:1.9rem; font-weight:800; line-height:1.05; color: var(--texto); }
.kpi .klab { font-size:.92rem; color:#334155; font-weight:600; }
.kpi .kayu { font-size:.78rem; color: var(--suave); }
.kpi.t-verde { border-left-color:#16A34A; } .kpi.t-verde .kico { background:#DCFCE7; }
.kpi.t-amarillo { border-left-color:#CA8A04; } .kpi.t-amarillo .kico { background:#FEF9C3; }
.kpi.t-naranja { border-left-color:#EA580C; } .kpi.t-naranja .kico { background:#FFEDD5; }
.kpi.t-rojo { border-left-color:#DC2626; } .kpi.t-rojo .kico { background:#FEE2E2; }
.kpi.t-morado { border-left-color:#7C3AED; } .kpi.t-morado .kico { background:#EDE9FE; }
.kpi.t-teal { border-left-color:#0EA5A4; } .kpi.t-teal .kico { background:#CCFBF1; }
/* Insignias de estado */
.badge { display:inline-block; padding:.12rem .6rem; border-radius:999px; font-weight:700; font-size:.85rem; border:1px solid rgba(0,0,0,.1); white-space:nowrap; }
.b-verde { background:#DCFCE7; color:#14532D; } .b-amarillo { background:#FEF9C3; color:#713F12; }
.b-naranja { background:#FFEDD5; color:#9A3412; } .b-rojo { background:#FEE2E2; color:#7F1D1D; }
.b-azul { background:#DBEAFE; color:#1E3A8A; } .b-gris { background:#F1F5F9; color:#334155; }
.b-morado { background:#EDE9FE; color:#4C1D95; } .b-teal { background:#CCFBF1; color:#115E59; }
/* Tarjetas */
.card { background:#fff; border:1px solid var(--borde); border-radius: var(--radio); padding:1rem 1.2rem; box-shadow: var(--sombra); margin-bottom:.8rem; }
.card h4 { margin:0 0 .3rem 0; color:var(--azul); }
.card .sub { color: var(--suave); font-size:.92rem; }
.vacio { text-align:center; padding:1.6rem 1rem; background:#fff; border:2px dashed #CBD5E1; border-radius:16px; color:#334155; }
.vacio .vico { font-size:2.6rem; } .vacio .vtit { font-weight:800; color:var(--azul); font-size:1.15rem; }
.paso { background:#fff; border:1px solid var(--borde); border-radius:14px; padding:.9rem 1rem; box-shadow: var(--sombra); height:100%; }
.paso .n { display:inline-flex; width:34px; height:34px; border-radius:50%; background:var(--teal); color:#fff; font-weight:800; align-items:center; justify-content:center; margin-right:.5rem; }
.rotulo-qr { border:2px dashed var(--azul2); border-radius:14px; padding:.8rem; background:#fff; text-align:center; }
.linea-tiempo { border-left:4px solid var(--teal); margin-left:.6rem; padding-left:1rem; }
.linea-tiempo .hito { margin-bottom:.7rem; position:relative; }
.linea-tiempo .hito::before { content:""; position:absolute; left:-1.4rem; top:.35rem; width:14px; height:14px; border-radius:50%; background:var(--teal); border:3px solid #fff; box-shadow:0 0 0 2px var(--teal); }
.barra { background:#E2E8F0; border-radius:999px; height:12px; overflow:hidden; } .barra > div { height:100%; border-radius:999px; }
/* Botones de acceso rápido (st.page_link) */
[data-testid="stPageLink"] a { background:#fff; border:1px solid var(--borde); border-radius:12px; padding:.75rem 1rem; font-weight:700; box-shadow: var(--sombra); }
[data-testid="stPageLink"] a:hover { border-color: var(--azul2); background:#F0F6FF; }
/* Pie de página en TODAS las pantallas */
.pie-atm { position:fixed; left:0; right:0; bottom:0; z-index:99; background: linear-gradient(90deg,#0B2540,#12355B); color:#E2E8F0;
           text-align:center; padding:.4rem 1rem; font-size:.92rem; letter-spacing:.03em; border-top:3px solid var(--teal); }
.pie-atm b { color: var(--teal-claro); font-weight:800; }
/* Proyector: texto un poco mayor en pantallas anchas */
@media (min-width: 1600px) { html, body, [class*="css"] { font-size: 17px; } }
</style>
"""


def estilos():
    st.markdown(CSS, unsafe_allow_html=True)


def pie():
    """Pie de página fijo, visible en cada pantalla (se dibuja desde Inicio.py antes de ejecutar la página)."""
    st.markdown(f"<div class='pie-atm' role='contentinfo'>{html.escape(PIE_TEXTO.split(' by ')[0])} by "
                f"<b>{html.escape(PIE_TEXTO.split(' by ')[1])}</b></div>", unsafe_allow_html=True)


def esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


def hero(titulo: str, subtitulo: str = "", icono: str = "", chips: list[str] | None = None):
    ch = "".join(f"<span class='chip'>{esc(c)}</span>" for c in (chips or []))
    st.markdown(f"<div class='hero'><div class='ico'>{esc(icono)}</div><div><h2>{esc(titulo)}</h2><p>{esc(subtitulo)}</p>"
                f"{f'<div class=chips>{ch}</div>' if ch else ''}</div></div>", unsafe_allow_html=True)


def kpis(items: list[tuple]):
    """items: (icono, etiqueta, valor, tono, ayuda). Tonos: azul, verde, amarillo, naranja, rojo, morado, teal."""
    celdas = []
    for it in items:
        ico, lab, val, tono, ayu = (list(it) + ["azul", ""])[:5] if len(it) < 5 else it
        celdas.append(f"<div class='kpi t-{esc(tono)}'><div class='kico'>{esc(ico)}</div><div><div class='kval'>{esc(val)}</div>"
                      f"<div class='klab'>{esc(lab)}</div>{f'<div class=kayu>{esc(ayu)}</div>' if ayu else ''}</div></div>")
    st.markdown(f"<div class='kpi-grid'>{''.join(celdas)}</div>", unsafe_allow_html=True)


def badge(texto: str, tono: str = "gris") -> str:
    return f"<span class='badge b-{esc(tono)}'>{esc(texto)}</span>"


def vacio(icono: str, titulo: str, texto: str = ""):
    st.markdown(f"<div class='vacio'><div class='vico'>{esc(icono)}</div><div class='vtit'>{esc(titulo)}</div>"
                f"<div>{esc(texto)}</div></div>", unsafe_allow_html=True)


def tarjeta(titulo: str, cuerpo: str = "", sub: str = ""):
    st.markdown(f"<div class='card'><h4>{esc(titulo)}</h4>{f'<div class=sub>{esc(sub)}</div>' if sub else ''}{cuerpo}</div>",
                unsafe_allow_html=True)


def barra(pct: float, tono: str = "#0EA5A4") -> str:
    p = max(0, min(100, pct))
    color = "#16A34A" if p < 70 else ("#CA8A04" if p < 90 else "#DC2626") if tono == "auto" else tono
    return f"<div class='barra'><div style='width:{p}%;background:{color}'></div></div>"
