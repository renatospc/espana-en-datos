"""Estilos matplotlib desde `global.json` (`benchmarks[].estilo`, TAD §4)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import math

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter, MaxNLocator

from .ccaa import NOMBRES_CCAA

GLOBAL = Path(__file__).resolve().parent.parent / "global.json"

# Debe cubrir el enum `trazo` de src/lib/schema.ts (lo comprueba tests/test_estilos.py).
TRAZOS: dict[str, Any] = {
    "solido": "-",
    "discontinuo": "--",
    "punteado": ":",
    "raya_punto": "-.",
    "raya_larga": (0, (8, 3)),
}

MODOS = ("claro", "oscuro")

# Superficie, texto principal y secundario, y rejilla por modo (la rejilla, un paso por encima de la superficie).
PALETA = {
    "claro": {"fondo": "#FFFFFF", "texto": "#111827", "texto_sec": "#6B7280", "rejilla": "#E5E7EB"},
    "oscuro": {"fondo": "#111827", "texto": "#F9FAFB", "texto_sec": "#9CA3AF", "rejilla": "#374151"},
}
# La web usa la tipografía del sistema; en los notebooks, la primera sans disponible.
TIPOGRAFIAS = ["Inter", "Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"]
ATRIBUCION = "España en Datos"

ROTULOS_CCAA = 3  # en `por_ccaa`, se rotulan las comunidades con el último valor más alto


def _benchmarks() -> list[dict]:
    return json.loads(GLOBAL.read_text(encoding="utf-8"))["benchmarks"]


def estilo_benchmark(id: str, modo: str = "claro") -> dict[str, Any]:
    """Argumentos de `ax.plot` (color, linestyle, linewidth, label) de un benchmark."""
    if modo not in MODOS:
        raise ValueError(f"modo desconocido: {modo!r}; válidos: {', '.join(MODOS)}")
    for b in _benchmarks():
        if b["id"] == id:
            e = b["estilo"]
            return {
                "color": e[f"color_{modo}"],
                "linestyle": TRAZOS[e["trazo"]],
                "linewidth": e["grosor"],
                "label": b["nombre"],
            }
    raise KeyError(f"benchmark desconocido: {id!r}")


def _paleta(modo: str) -> dict[str, str]:
    if modo not in MODOS:
        raise ValueError(f"modo desconocido: {modo!r}; válidos: {', '.join(MODOS)}")
    return PALETA[modo]


def formato_es(x: float, decimales: int | None = None) -> str:
    """Número con coma decimal y punto de miles (1.234,5). Sin `decimales`, 0 si es entero y 1 si no."""
    if decimales is None:
        decimales = 0 if float(x).is_integer() else 1
    texto = f"{x:,.{decimales}f}"
    return texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def aplicar_estilos(modo: str = "claro") -> None:
    """Ajustes globales de matplotlib: sin caja, rejilla horizontal fina y texto secundario en los ejes."""
    p = _paleta(modo)
    plt.rcParams.update(
        {
            "figure.facecolor": p["fondo"],
            "axes.facecolor": p["fondo"],
            "savefig.facecolor": p["fondo"],
            "figure.figsize": (10, 6),
            "figure.dpi": 110,
            "savefig.dpi": 200,
            "font.family": "sans-serif",
            "font.sans-serif": TIPOGRAFIAS,
            "font.size": 11,
            "text.color": p["texto"],
            "axes.labelcolor": p["texto_sec"],
            "axes.edgecolor": p["rejilla"],
            "axes.linewidth": 1,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.spines.left": False,
            "axes.grid": True,
            "axes.grid.axis": "y",
            "axes.axisbelow": True,
            "grid.color": p["rejilla"],
            "grid.linestyle": "-",
            "grid.linewidth": 1,
            "grid.alpha": 1,
            "xtick.color": p["texto_sec"],
            "ytick.color": p["texto_sec"],
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "xtick.major.size": 0,
            "ytick.major.size": 0,
            "xtick.major.pad": 6,
            "ytick.major.pad": 6,
            "legend.frameon": False,
            "legend.fontsize": 10,
            "lines.solid_capstyle": "round",
            "lines.solid_joinstyle": "round",
        }
    )


def _ultimo(valores: list) -> int | None:
    return next((i for i in range(len(valores) - 1, -1, -1) if valores[i] is not None), None)


def dibujar_series(ax, datos: dict, modo: str = "claro", referencia: float | None = None) -> None:
    """Dibuja `series` de un `GraficaData` ya construido.

    `serie_temporal` y `solo_espana` usan los estilos de los benchmarks; en `por_ccaa` las
    comunidades van en gris fino con `espana` destacada. Cada serie acaba en un punto (también se
    marcan los datos aislados, sin vecinos con los que formar línea) y solo
    `espana` lleva el último valor como etiqueta. `referencia` dibuja una línea horizontal
    (p. ej. 100 en un índice). La unidad no va en el eje: la pone `componer` como subtítulo.
    """
    p = _paleta(modo)
    años = [int(x) for x in datos["labels"]]
    por_benchmark = datos["tipo"] in ("serie_temporal", "solo_espana")
    if referencia is not None:
        ax.axhline(referencia, color=p["texto_sec"], linewidth=1, zorder=1)
    for clave, valores in datos["series"].items():
        if all(v is None for v in valores):
            continue  # sin ningún dato: ni línea ni entrada en la leyenda (lo explican las notas)
        if por_benchmark:
            kw = estilo_benchmark(clave, modo)
        else:
            kw = {"label": clave, "linewidth": 3 if clave == "espana" else 1}
            kw["color"] = estilo_benchmark("espana", modo)["color"] if clave == "espana" else "#9CA3AF"
        destacada = clave == "espana"
        (linea,) = ax.plot(
            años, [math.nan if v is None else v for v in valores], zorder=3 if destacada else 2, **kw
        )
        # Un dato sin vecinos no forma línea: se marca con un punto para que se vea
        aislados = [
            j for j, v in enumerate(valores)
            if v is not None
            and (j == 0 or valores[j - 1] is None)
            and (j == len(valores) - 1 or valores[j + 1] is None)
        ]
        if aislados:
            ax.plot(
                [años[j] for j in aislados], [valores[j] for j in aislados], "o",
                markersize=9 if destacada else 8, color=linea.get_color(),
                markeredgecolor=p["fondo"], markeredgewidth=1.5, zorder=4, label="_nolegend_",
            )
        i = _ultimo(valores)
        if i is None:
            continue
        if i not in aislados:  # un dato aislado ya lleva su punto, más grande
            ax.plot(
                años[i], valores[i], "o", markersize=7 if destacada else 5, color=linea.get_color(),
                markeredgecolor=p["fondo"], markeredgewidth=1.5, zorder=5 if destacada else 4, label="_nolegend_",
            )
        if destacada:
            ax.annotate(
                formato_es(valores[i]), xy=(años[i], valores[i]), xytext=(8, 0),
                textcoords="offset points", va="center", fontsize=11, fontweight="bold",
                color=p["texto"], annotation_clip=False,
            )
    # El eje empieza en el primer año con algún dato (el JSON sigue empezando en `desde`)
    primero = min(
        (años[j] for v in datos["series"].values() for j, x in enumerate(v) if x is not None), default=años[0]
    )
    margen = max(0.3, (años[-1] - primero) * 0.015)  # que los puntos de los extremos no queden cortados
    ax.set_xlim(primero - margen, años[-1] + margen)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    if not por_benchmark:
        _rotular_ccaa(ax, datos, años, p)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: formato_es(x)))
    con_datos = [k for k, v in datos["series"].items() if any(x is not None for x in v)]
    if len(con_datos) <= 1:
        return  # una sola serie: el título ya dice qué se ve, sin leyenda
    if por_benchmark:
        ax.legend(loc="lower left", bbox_to_anchor=(0, 1.02), ncol=len(con_datos), handlelength=2.6)
    else:
        claves = [
            Line2D([], [], color=estilo_benchmark("espana", modo)["color"], linewidth=3, label="España"),
            Line2D([], [], color="#9CA3AF", linewidth=1, label="Comunidades autónomas"),
        ]
        ax.legend(handles=claves, loc="lower left", bbox_to_anchor=(0, 1.02), ncol=2, handlelength=2.6)


def _rotular_ccaa(ax, datos: dict, años: list[int], p: dict[str, str]) -> None:
    """Nombre al final de las comunidades con el último valor más alto (las demás, en la tabla)."""
    finales = []
    for clave, valores in datos["series"].items():
        i = _ultimo(valores)
        if clave != "espana" and i is not None:
            finales.append((valores[i], años[i], clave))
    for v, a, clave in sorted(finales, reverse=True)[:ROTULOS_CCAA]:
        ax.annotate(
            NOMBRES_CCAA.get(clave, clave), xy=(a, v), xytext=(8, 0), textcoords="offset points",
            va="center", fontsize=9, color=p["texto_sec"], annotation_clip=False,
        )


def componer(fig, ax, *, titulo: str, datos: dict, modo: str = "claro") -> None:
    """Encabezado y pie de la figura: título, unidad, leyenda en una fila y fuentes con licencia."""
    p = _paleta(modo)
    x = 0.02
    fig.subplots_adjust(left=0.07, right=0.92, top=0.8, bottom=0.11)
    fig.text(x, 0.965, titulo, ha="left", va="top", fontsize=16, fontweight="bold", color=p["texto"])
    fig.text(x, 0.905, datos["unidad"], ha="left", va="top", fontsize=11, color=p["texto_sec"])
    leyenda = ax.get_legend()
    if leyenda is not None:
        claves = leyenda.legend_handles
        etiquetas = [t.get_text() for t in leyenda.get_texts()]
        leyenda.remove()
        fig.legend(
            claves, etiquetas, loc="upper left", bbox_to_anchor=(x - 0.005, 0.875), ncol=len(claves),
            handlelength=2.6, columnspacing=1.6, labelcolor=p["texto"],
        )
    # Solo las fuentes de las series con datos (las consultadas sin dato se explican en las notas)
    con_datos = {k for k, v in datos["series"].items() if any(x is not None for x in v)}
    organismos = list(dict.fromkeys(
        f["organismo"] for f in datos["fuentes"] if "serie" not in f or f["serie"] in con_datos
    ))
    fig.text(
        x, 0.025, f"Fuente: {', '.join(organismos)} · Licencia CC BY 4.0 · {ATRIBUCION}",
        ha="left", va="bottom", fontsize=9, color=p["texto_sec"],
    )
