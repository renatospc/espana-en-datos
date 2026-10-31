"""Estilos matplotlib desde `global.json` (`benchmarks[].estilo`, TAD §4)."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import math
import textwrap

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter, MaxNLocator

from .ccaa import NOMBRES_CCAA
from .paises import NOMBRES_AGREGADOS, nombre_punto

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

# Debe coincidir con el enum `vista` de src/lib/schema.ts (lo comprueba tests/test_estilos.py): cada vista
# de la web tiene su dibujo aquí, para que el notebook muestre la misma gráfica que la web.
VISTAS = ("lineas", "ultimo_anio", "proyeccion", "categorias", "composicion")
# Colores de las partes en la vista `composicion`, por modo: los tokens `TOKENS_PARTES` de src/lib/estilos-series.ts
# en src/app/globals.css (lo comprueba tests/test_estilos.py), primero enteros y después con OPACIDAD_PARTES.
COLORES_PARTES = {
    "claro": ["#216B70", "#5B7CFA", "#9585E8", "#C58A2B", "#527093"],
    "oscuro": ["#7FD0CA", "#8AA2FF", "#B3A7F2", "#E0AA52", "#A3B7CB"],
}
OPACIDAD_PARTES = 0.5
# Se rotula con su valor la parte que ocupa al menos esta fracción del eje, como ROTULO_PARTES de la web.
ROTULO_PARTES = 0.06

# Superficie, texto principal y secundario, y rejilla por modo (la rejilla, un paso por encima de la superficie).
PALETA = {
    "claro": {"fondo": "#FFFFFF", "texto": "#183653", "texto_sec": "#527093", "rejilla": "#E8EFF3"},
    "oscuro": {"fondo": "#0D1B2A", "texto": "#DBE6F0", "texto_sec": "#A3B7CB", "rejilla": "#24405B"},
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


# Gris de las partes de un desglose, como GRIS_NEUTRO de src/lib/estilos-series.ts.
GRIS_NEUTRO = {"claro": "#7890A8", "oscuro": "#8197AE"}
# Trazos de las partes de un desglose (en gris, para que España siga destacada), como DASH_DESGLOSE de la web.
TRAZOS_DESGLOSE = [(0, (7, 4)), (0, (2, 4)), (0, (8, 3, 2, 3))]
# Comunidades en `por_ccaa`: gris fino, como `estiloSerie` de la web.
GROSOR_CCAA = 1.25
# Años proyectados (`proyeccion` de los datos): trazo de puntos, como TRAZO_PROYECCION de PanelGrafica.tsx
# (en matplotlib, las rayas se miden en grosores de línea).
TRAZO_PROYECCION = (0, (1, 2.5))


def estilo_desglose(clave: str, datos: dict, modo: str = "claro") -> dict[str, Any]:
    """Estilo de una parte del desglose de `espana` (`desglose`): gris, con un trazo por parte."""
    claves = list(datos["desglose"])
    return {
        "label": datos["desglose"][clave],
        "color": GRIS_NEUTRO[modo],
        "linestyle": TRAZOS_DESGLOSE[claves.index(clave) % len(TRAZOS_DESGLOSE)],
        "linewidth": 2,
    }


def estilo_categoria(clave: str, datos: dict, modo: str = "claro") -> dict[str, Any]:
    """Estilo de una de las `categorias` en líneas: el color y el trazo del benchmark de su posición, como `estiloDe` de src/lib/estilos-series.ts."""
    bs = _benchmarks()
    return {**estilo_benchmark(bs[list(datos["categorias"]).index(clave) % len(bs)]["id"], modo), "label": datos["categorias"][clave]}


def _paleta(modo: str) -> dict[str, str]:
    if modo not in MODOS:
        raise ValueError(f"modo desconocido: {modo!r}; válidos: {', '.join(MODOS)}")
    return PALETA[modo]


def formato_es(x: float, decimales: int | None = None) -> str:
    """Número con coma decimal y punto de miles solo a partir de cinco cifras enteras (1234,5; 12.345), como
    pide la RAE y como `formatoNumero` de src/lib/grafica.ts. Sin `decimales`, 0 si es entero y 1 si no."""
    if decimales is None:
        decimales = 0 if float(x).is_integer() else 1
    entero, _, fraccion = f"{x:.{decimales}f}".partition(".")
    signo, entero = ("-", entero[1:]) if entero.startswith("-") else ("", entero)
    if len(entero) >= 5:
        entero = f"{int(entero):,}".replace(",", ".")
    return signo + entero + (f",{fraccion}" if fraccion else "")


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


def partir_proyeccion(serie: list, labels: list[str], desde: str | None) -> tuple[list, list | None]:
    """Serie observada (hasta el periodo anterior a `desde`) y proyectada (desde el último observado, para
    que la línea no se corte), como `partirProyeccion` de src/lib/grafica.ts. Sin `desde` o si no cae en
    `labels`, toda es observada; si es anterior al primer periodo, toda es proyectada."""
    if desde is None:
        return list(serie), None
    if desde in labels:
        i0 = labels.index(desde)
    elif labels and int(desde) < int(labels[0]):
        i0 = 0
    else:
        return list(serie), None
    return (
        [v if i < i0 else None for i, v in enumerate(serie)],
        [v if i >= i0 - 1 else None for i, v in enumerate(serie)],
    )


def ultimo_indice_comun(datos: dict) -> int | None:
    """Último periodo con dato en todas las series que tienen alguno (vista de categorías), como
    `ultimoIndiceComun` de src/lib/grafica.ts."""
    con = [v for v in datos["series"].values() if any(x is not None for x in v)]
    if not con:
        return None
    return next((i for i in range(len(datos["labels"]) - 1, -1, -1) if all(v[i] is not None for v in con)), None)


def dibujar_series(ax, datos: dict, modo: str = "claro") -> None:
    """Dibuja `series` de un `GraficaData` ya construido.

    `serie_temporal` y `solo_espana` usan los estilos de los benchmarks; en `por_ccaa` las
    comunidades van en gris fino con `espana` destacada. Cada serie acaba en un punto (también se
    marcan los datos aislados, sin vecinos con los que formar línea) y solo
    `espana` lleva el último valor como etiqueta. Si `datos` trae `referencia`, dibuja una línea
    horizontal en ese valor (p. ej. 100 en un índice), como la web. La unidad no va en el eje: la
    pone `componer` como subtítulo.
    """
    p = _paleta(modo)
    años = [int(x) for x in datos["labels"]]
    por_benchmark = datos["tipo"] in ("serie_temporal", "solo_espana")
    proyecciones = datos.get("proyeccion") or {}
    if datos.get("referencia") is not None:
        ax.axhline(datos["referencia"], color=p["texto_sec"], linewidth=1, zorder=1)
    desde = sorted(x["desde"] for x in proyecciones.values() if x["desde"] in datos["labels"])
    hay_observados = any(
        x is not None
        for k, v in datos["series"].items()
        for x in partir_proyeccion(v, datos["labels"], proyecciones.get(k, {}).get("desde"))[0]
    )
    if desde and hay_observados:  # línea vertical donde empiezan los años proyectados; si todo es proyección, sobra
        ax.axvline(int(desde[0]), color=p["rejilla"], linewidth=1, linestyle=(0, (4, 4)), zorder=1)
        ax.annotate(
            "Proyección", xy=(int(desde[0]), 1), xycoords=("data", "axes fraction"), xytext=(4, -4),
            textcoords="offset points", ha="left", va="top", fontsize=9, color=p["texto_sec"],
        )
    for clave, valores in datos["series"].items():
        if all(v is None for v in valores):
            continue  # sin ningún dato: ni línea ni entrada en la leyenda (lo explican las notas)
        if clave in datos.get("desglose", {}):
            kw = estilo_desglose(clave, datos, modo)
        elif clave in datos.get("categorias", {}):
            kw = estilo_categoria(clave, datos, modo)
        elif por_benchmark:
            kw = estilo_benchmark(clave, modo)
        elif clave == "espana":
            kw = {**estilo_benchmark("espana", modo), "linestyle": "-", "label": clave}
        else:
            kw = {"label": clave, "linewidth": GROSOR_CCAA, "color": GRIS_NEUTRO[modo]}
        destacada = clave == "espana"
        observada, proyectada = partir_proyeccion(valores, datos["labels"], proyecciones.get(clave, {}).get("desde"))
        hay_observada = any(v is not None for v in observada)
        if proyectada is not None:
            # Las proyecciones se publican a veces cada cinco años: la línea une los años con dato, como la web
            con = [(años[j], v) for j, v in enumerate(proyectada) if v is not None]
            (linea,) = ax.plot(
                [a for a, _ in con], [v for _, v in con], zorder=3 if destacada else 2,
                **{**kw, "linestyle": TRAZO_PROYECCION, "label": "_nolegend_" if hay_observada else kw["label"]},
            )
        if hay_observada or proyectada is None:
            (linea,) = ax.plot(
                años, [math.nan if v is None else v for v in observada], zorder=3 if destacada else 2, **kw
            )
        # Un dato sin vecinos no forma línea: se marca con un punto para que se vea
        aislados = [
            j for j, v in enumerate(observada)
            if v is not None
            and (j == 0 or observada[j - 1] is None)
            and (j == len(observada) - 1 or observada[j + 1] is None)
        ]
        if aislados:
            ax.plot(
                [años[j] for j in aislados], [observada[j] for j in aislados], "o",
                markersize=9 if destacada else 8, color=linea.get_color(),
                markeredgecolor=p["fondo"], markeredgewidth=1.5, zorder=4, label="_nolegend_",
            )
        # Punto al final de la serie observada (si no es un dato aislado, que ya lleva el suyo) y de la proyectada
        finales = [i for i in (_ultimo(observada),) if i is not None and i not in aislados]
        if proyectada is not None and _ultimo(proyectada) is not None:
            finales.append(_ultimo(proyectada))
        for i in finales:
            ax.plot(
                años[i], valores[i], "o", markersize=7 if destacada else 5, color=linea.get_color(),
                markeredgecolor=p["fondo"], markeredgewidth=1.5, zorder=5 if destacada else 4, label="_nolegend_",
            )
        j = _ultimo(observada)
        if destacada and j is not None:
            ax.annotate(
                formato_es(observada[j]), xy=(años[j], observada[j]), xytext=(8, 0),
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
            Line2D([], [], color=estilo_benchmark("espana", modo)["color"],
                   linewidth=estilo_benchmark("espana", modo)["linewidth"], label="España"),
            Line2D([], [], color=GRIS_NEUTRO[modo], linewidth=GROSOR_CCAA, label="Comunidades autónomas"),
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


def componer(
    fig, ax, *, titulo: str, datos: dict, modo: str = "claro", subtitulo: str | None = None, izquierda: float = 0.07
) -> None:
    """Encabezado y pie de la figura: título, unidad (o `subtitulo`), leyenda en una fila y fuentes con
    licencia; los años proyectados se explican en las notas, como en la web. Las distancias van en pulgadas
    desde el borde, para que las figuras más altas (barras por comunidad) tengan la misma cabecera y el mismo pie."""
    p = _paleta(modo)
    x = 0.02
    alto = fig.get_figheight()
    arriba = lambda pulgadas: 1 - pulgadas / alto  # noqa: E731
    abajo = lambda pulgadas: pulgadas / alto  # noqa: E731
    fig.subplots_adjust(left=izquierda, right=0.92, top=arriba(1.2), bottom=abajo(0.66))
    fig.text(x, arriba(0.21), titulo, ha="left", va="top", fontsize=16, fontweight="bold", color=p["texto"])
    fig.text(x, arriba(0.57), subtitulo or datos["unidad"], ha="left", va="top", fontsize=11, color=p["texto_sec"])
    leyenda = ax.get_legend()
    if leyenda is not None:
        claves = leyenda.legend_handles
        etiquetas = [t.get_text() for t in leyenda.get_texts()]
        leyenda.remove()
        fig.legend(
            claves, etiquetas, loc="upper left", bbox_to_anchor=(x - 0.005, arriba(0.75)), ncol=len(claves),
            handlelength=2.6, columnspacing=1.6, labelcolor=p["texto"],
        )
    # Solo las fuentes de las series con datos (las consultadas sin dato se explican en las notas)
    con_datos = {k for k, v in datos["series"].items() if any(x is not None for x in v)}
    organismos = list(dict.fromkeys(
        f["organismo"] for f in datos["fuentes"] if "serie" not in f or f["serie"] in con_datos
    ))
    fig.text(
        x, abajo(0.15), f"Fuente: {', '.join(organismos)} · Licencia CC BY 4.0 · {ATRIBUCION}",
        ha="left", va="bottom", fontsize=9, color=p["texto_sec"],
    )


def _nombre_serie(clave: str, datos: dict, modo: str) -> str:
    """Nombre de una serie para leyendas y notas: parte del desglose, categoría, benchmark o comunidad."""
    nombradas = datos.get("desglose") or datos.get("categorias") or {}
    if clave in nombradas:
        return nombradas[clave]
    if datos["tipo"] != "por_ccaa" or clave == "espana":
        try:
            return estilo_benchmark(clave, modo)["label"]
        except KeyError:
            pass
    return NOMBRES_CCAA.get(clave, clave)


# ---------- Vistas de barras (`vista` del config), como PanelUltimoAnio.tsx y PanelCategorias.tsx ----------

FILA_BARRAS = 0.3  # alto de cada barra por comunidad, en pulgadas
FILA_CATEGORIAS = 0.55  # las categorías, con el nombre en hasta tres líneas
ANCHO_NOMBRE = 24  # caracteres por línea del nombre de una categoría, como en la web


def escala(valores: list[float], max_ticks: int = 6) -> list[float]:
    """Marcas «redondas» del eje que cubren los valores, como `escalaY` de src/lib/grafica.ts."""
    if not valores:
        return [0, 1]
    max_ticks = max(max_ticks, 3)
    lo, hi = min(valores), max(valores)
    if lo == hi:
        d = abs(lo) * 0.1 or 1
        lo, hi = lo - d, hi + d
    mag = 10 ** math.floor(math.log10((hi - lo) / (max_ticks - 1)))
    while True:
        for m in (1, 2, 2.5, 5):
            paso = m * mag
            a = math.floor(round(lo / paso, 9)) * paso
            b = math.ceil(round(hi / paso, 9)) * paso
            n = round((b - a) / paso) + 1
            if n <= max_ticks:
                return [round(a + i * paso, 10) for i in range(n)]
        mag *= 10


def _eje_barras(ax, ticks: list[float], p: dict[str, str]) -> None:
    """Eje de valores horizontal con rejilla vertical, sin rejilla horizontal."""
    ax.set_xlim(ticks[0], ticks[-1])
    ax.set_xticks(ticks)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: formato_es(v)))
    ax.grid(False, axis="y")
    ax.grid(True, axis="x")
    ax.spines["bottom"].set_visible(True)
    ax.spines["bottom"].set_color(p["rejilla"])
    ax.tick_params(axis="y", length=0)


def periodo_ultimo_anio(datos: dict) -> tuple[int, str] | None:
    """Índice y periodo del último año con dato de España, como `ultimoPeriodo` de la web."""
    i = _ultimo(datos["series"].get("espana", []))
    return None if i is None else (i, datos["labels"][i])


def dibujar_ultimo_anio(ax, datos: dict, eje_max: float | None = None, modo: str = "claro") -> None:
    """Vista `ultimo_anio`: solo el último año con dato de España.

    En `por_ccaa`, una barra horizontal por comunidad, de mayor a menor, y otra destacada para España;
    cada barra llega hasta el final del eje (`eje_max`, p. ej. 100) con la parte clara. En `solo_espana`
    con `desglose`, una barra apilada con cada parte, del color de España con menos opacidad.
    """
    p = _paleta(modo)
    color_espana = estilo_benchmark("espana", modo)["color"]
    ultimo = periodo_ultimo_anio(datos)
    if ultimo is None:
        return
    i, _ = ultimo
    extra = [eje_max] if eje_max else []
    if datos.get("desglose"):
        partes = list(datos["desglose"])
        valor = lambda k: datos["series"][k][i] or 0  # noqa: E731
        ticks = escala([0, valor("espana"), *extra])
        izquierda = 0.0
        for n, k in enumerate(partes):
            alfa = 1 - n * (0.55 / max(len(partes), 1))
            ax.barh(0, valor(k), left=izquierda, height=0.5, color=color_espana, alpha=alfa,
                    label=f"{datos['desglose'][k]}: {formato_es(valor(k), 1)}")
            izquierda += valor(k)
        ax.set_yticks([])
        ax.set_ylim(-0.6, 0.6)
        _eje_barras(ax, ticks, p)
        ax.legend(loc="lower left", bbox_to_anchor=(0, 1.02), ncol=len(partes), handlelength=1.2)
        ax.annotate(
            f"Total: {formato_es(valor('espana'), 1)}", xy=(1, 1.02), xycoords="axes fraction",
            ha="right", va="bottom", fontsize=10, fontweight="bold", color=p["texto"],
        )
        return
    filas = sorted(
        ((v[i], clave) for clave, v in datos["series"].items() if v[i] is not None), reverse=True
    )
    ticks = escala([0, *(v for v, _ in filas), *extra])
    fin = ticks[-1]
    y = list(range(len(filas)))[::-1]  # la mayor, arriba
    for yy, (v, clave) in zip(y, filas):
        espana = clave == "espana"
        ax.barh(yy, v, height=0.8, color=color_espana if espana else GRIS_NEUTRO[modo], zorder=3)
        ax.barh(yy, max(fin - v, 0), left=v, height=0.8, color=p["rejilla"], alpha=0.6, zorder=3)
        ax.annotate(
            formato_es(v, 1), xy=(v, yy), xytext=(4, 0), textcoords="offset points", va="center",
            fontsize=9, color=p["texto_sec"], zorder=4,
        )
    ax.set_yticks(y, [_nombre_serie(c, datos, modo) for _, c in filas])
    for etiqueta, (_, clave) in zip(ax.get_yticklabels(), filas):
        if clave == "espana":
            etiqueta.set_color(color_espana)
            etiqueta.set_fontweight("bold")
    ax.set_ylim(-0.6, len(filas) - 0.4)
    _eje_barras(ax, ticks, p)


def dibujar_categorias(ax, datos: dict, eje_max: float | None = None, modo: str = "claro") -> None:
    """Vista `categorias`: una barra horizontal por categoría en el último año con dato de todas, en el
    orden en que se declaran, del color de España y con su valor al final."""
    p = _paleta(modo)
    if not datos.get("categorias"):
        raise ValueError("la vista de categorías necesita `categorias` en los datos")
    i = ultimo_indice_comun(datos)
    if i is None:
        raise ValueError("ningún año reúne a todas las categorías con datos")
    filas = [(k, n, datos["series"][k][i]) for k, n in datos["categorias"].items() if datos["series"][k][i] is not None]
    ticks = escala([0, *(v for _, _, v in filas), *([eje_max] if eje_max else [])])
    y = list(range(len(filas)))[::-1]  # la primera, arriba
    color = estilo_benchmark("espana", modo)["color"]
    for yy, (_, _, v) in zip(y, filas):
        ax.barh(yy, v, height=0.5, color=color, zorder=3)
        ax.annotate(formato_es(v, 1), xy=(v, yy), xytext=(4, 0), textcoords="offset points", va="center",
                    fontsize=10, color=p["texto_sec"], zorder=4, annotation_clip=False)
    ax.set_yticks(y, [textwrap.fill(n, ANCHO_NOMBRE) for _, n, _ in filas])
    ax.set_ylim(-0.6, len(filas) - 0.4)
    _eje_barras(ax, ticks, p)


def ultimo_indice_completo(datos: dict, benchmark: str) -> int | None:
    """Último periodo con dato de todas las partes de `composicion` de un benchmark."""
    partes = list(datos["composicion"])
    for i in range(len(datos["labels"]) - 1, -1, -1):
        if all(datos["series"][f"{benchmark}__{k}"][i] is not None for k in partes):
            return i
    return None


def estilo_parte(n: int, modo: str = "claro") -> tuple[str, float]:
    """Color y opacidad de la parte `n` de `composicion`: los colores de COLORES_PARTES y, cuando se acaban,
    los mismos con OPACIDAD_PARTES (como `estiloParte` de la web)."""
    colores = COLORES_PARTES[modo]
    return colores[n % len(colores)], 1.0 if n < len(colores) else OPACIDAD_PARTES


def _luminancia(color: str) -> float:
    canales = [int(color.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    r, g, b = (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in canales)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a: str, b: str) -> float:
    """Contraste WCAG entre dos colores hexadecimales (de 1 a 21)."""
    la, lb = sorted((_luminancia(a), _luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def color_rotulo(color: str, alfa: float, modo: str = "claro") -> str:
    """Color del valor rotulado dentro de una parte: el fondo claro o el oscuro, el que más contraste con la parte
    (mezclada con el fondo según su opacidad), como el `rotulo` de `estiloParte` en la web."""
    fondo = _paleta(modo)["fondo"].lstrip("#")
    c = color.lstrip("#")
    mezcla = "#" + "".join(
        f"{round(int(c[i:i + 2], 16) * alfa + int(fondo[i:i + 2], 16) * (1 - alfa)):02X}" for i in (0, 2, 4)
    )
    return max((PALETA["claro"]["fondo"], PALETA["oscuro"]["fondo"]), key=lambda t: contraste(t, mezcla))


def dibujar_composicion(ax, datos: dict, modo: str = "claro") -> None:
    """Vista `composicion`: una barra horizontal apilada por benchmark con sus partes de `composicion`, en su
    último año con dato de todas (que va junto al nombre), en el orden de la cesta. Cada parte lleva su valor si
    ocupa al menos ROTULO_PARTES del eje, en el color que más contraste con ella; un filo del color del fondo
    separa las partes."""
    p = _paleta(modo)
    if not datos.get("composicion"):
        raise ValueError("la vista de composición necesita `composicion` en los datos")
    partes = list(datos["composicion"])
    filas = []
    for b in _benchmarks():
        i = ultimo_indice_completo(datos, b["id"])
        if i is not None:
            filas.append((b["id"], b["nombre"], datos["labels"][i], [datos["series"][f"{b['id']}__{k}"][i] for k in partes]))
    if not filas:
        raise ValueError("ningún benchmark tiene dato de todas las partes")
    ticks = escala([0, max(sum(v) for *_r, v in filas)])
    y = list(range(len(filas)))[::-1]  # la primera de la cesta, arriba
    for yy, (_, _, _, valores) in zip(y, filas):
        izquierda = 0.0
        for n, v in enumerate(valores):
            color, alfa = estilo_parte(n, modo)
            ax.barh(yy, v, left=izquierda, height=0.6, color=color, alpha=alfa, edgecolor=p["fondo"], linewidth=0.8,
                    zorder=3, label=datos["composicion"][partes[n]] if yy == y[0] else None)
            if v >= ROTULO_PARTES * ticks[-1]:
                ax.annotate(formato_es(v, 0), xy=(izquierda + v / 2, yy), ha="center", va="center", fontsize=8,
                            color=color_rotulo(color, alfa, modo), zorder=4)
            izquierda += v
    ax.set_yticks(y, [f"{nombre} ({anio})" for _, nombre, anio, _ in filas])
    for etiqueta, (clave, *_rest) in zip(ax.get_yticklabels(), filas):
        if clave == "espana":
            etiqueta.set_color(estilo_benchmark("espana", modo)["color"])
            etiqueta.set_fontweight("bold")
    ax.set_ylim(-0.6, len(filas) - 0.4)
    _eje_barras(ax, ticks, p)


# ---------- Dispersión (METODOLOGIA §2.6), con las reglas de src/lib/dispersion.ts ----------

NOMBRADOS = ("USA", "CAN")  # además de España y las medias, llevan su nombre junto al punto


def clase_punto(codigo: str) -> str:
    """«espana», «nombrado» (EE. UU. y Canadá), «agregado» (medias) o «pais», como `clasePunto` de la web."""
    if codigo == "ESP":
        return "espana"
    if codigo in NOMBRADOS:
        return "nombrado"
    if codigo in NOMBRES_AGREGADOS:
        return "agregado"
    return "pais"


def titulo_eje(eje: dict) -> str:
    """«Cuña fiscal (% del coste laboral, 2023)», como `tituloEje` de la web."""
    return f"{eje['titulo']} ({eje['unidad']}, {eje['periodo']})"


def dibujar_dispersion(ax, datos: dict, modo: str = "claro") -> None:
    """Dibuja los `puntos` de un `GraficaDispersion` ya construido, sin línea de tendencia.

    Países en gris; España con el color de `espana`, más grande y con su nombre en negrita;
    Estados Unidos, Canadá y las medias (rombo) con su nombre. Rejilla en los dos ejes y títulos
    de eje con unidad y periodo.
    """
    p = _paleta(modo)
    color_espana = estilo_benchmark("espana", modo)["color"]
    peso = {"pais": 0, "nombrado": 1, "agregado": 2, "espana": 3}
    for pt in sorted(datos["puntos"], key=lambda q: peso[clase_punto(q["codigo"])]):
        clase = clase_punto(pt["codigo"])
        espana = clase == "espana"
        ax.scatter(
            pt["x"], pt["y"], s=110 if espana else 70 if clase == "agregado" else 45,
            marker="D" if clase == "agregado" else "o",
            color=color_espana if espana else GRIS_NEUTRO[modo],
            edgecolors=p["fondo"], linewidths=1.2, zorder=4 if espana else 3,
        )
        if clase != "pais":
            ax.annotate(
                nombre_punto(pt["codigo"]), xy=(pt["x"], pt["y"]), xytext=(7, 0), textcoords="offset points",
                va="center", fontsize=10 if espana else 9, fontweight="bold" if espana else "normal",
                color=p["texto"] if espana else p["texto_sec"], zorder=5,
            )
    ax.grid(True, axis="both")
    ax.spines["left"].set_visible(False)
    ax.set_xlabel(textwrap.fill(titulo_eje(datos["eje_x"]), 80))
    ax.set_ylabel(textwrap.fill(titulo_eje(datos["eje_y"]), 45))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: formato_es(v)))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: formato_es(v)))


NOMBRE_UNIVERSO = {"ocde": "OCDE", "ue27": "UE-27"}


def componer_dispersion(fig, ax, *, titulo: str, datos: dict, modo: str = "claro") -> None:
    """Encabezado y pie de una dispersión: título, universo y fuentes por eje con licencia."""
    p = _paleta(modo)
    x = 0.02
    fig.subplots_adjust(left=0.13, right=0.9, top=0.84, bottom=0.18)
    fig.text(x, 0.965, titulo, ha="left", va="top", fontsize=16, fontweight="bold", color=p["texto"])
    universo = NOMBRE_UNIVERSO.get(datos["universo"], datos["universo"])
    fig.text(
        x, 0.905, f"Un punto por país de la {universo} con dato en los dos indicadores",
        ha="left", va="top", fontsize=11, color=p["texto_sec"],
    )
    partes = []
    for eje in ("eje_x", "eje_y"):
        org = list(dict.fromkeys(f["organismo"] for f in datos["fuentes"] if f["serie"] == eje))
        if org:
            partes.append(f"{datos[eje]['titulo']}: {', '.join(org)}")
    fig.text(
        x, 0.02, f"Fuente: {'; '.join(partes)} · Licencia CC BY 4.0 · {ATRIBUCION}",
        ha="left", va="bottom", fontsize=9, color=p["texto_sec"],
    )


# ---------- Figura completa: lo que muestra el notebook ----------

ARCHIVOS_HUELLA = ("estilos.py", "ccaa.py", "paises.py")


def huella() -> str:
    """Huella de todo lo que decide cómo se dibuja una gráfica (este módulo, los nombres de comunidades y
    países y los estilos de `global.json`). `mostrar` la guarda en la salida del notebook y
    `python -m ci.notebooks comprobar` avisa de las imágenes dibujadas con otra versión."""
    h = hashlib.sha256()
    for nombre in ARCHIVOS_HUELLA:
        h.update((Path(__file__).parent / nombre).read_text(encoding="utf-8").replace("\r\n", "\n").encode())
    g = json.loads(GLOBAL.read_text(encoding="utf-8"))
    h.update(json.dumps({k: g[k] for k in ("benchmarks", "comunidades", "paises")}, sort_keys=True).encode())
    return h.hexdigest()[:16]


def figura(
    datos: dict, *, titulo: str, vista: str = "lineas", eje_max: float | None = None, modo: str = "claro"
):
    """La gráfica tal como la dibuja la web, según la `vista` y el `eje_max` de la gráfica en config.json.

    `lineas` y `proyeccion` son la evolución (con los años proyectados en trazo de puntos si los datos traen
    `proyeccion`); `ultimo_anio` y `categorias`, barras del último año, y `composicion`, una barra apilada por
    serie de la cesta. Las dispersiones (con `puntos`) tienen su propio dibujo. Devuelve la figura para pasarla
    a `mostrar`.
    """
    if vista not in VISTAS:
        raise ValueError(f"vista desconocida: {vista!r}; válidas: {', '.join(VISTAS)}")
    aplicar_estilos(modo)
    if "puntos" in datos:
        fig, ax = plt.subplots()
        dibujar_dispersion(ax, datos, modo)
        componer_dispersion(fig, ax, titulo=titulo, datos=datos, modo=modo)
        return fig
    if vista == "ultimo_anio":
        ultimo = periodo_ultimo_anio(datos)
        filas = 1  # la barra apilada del desglose, o ninguna sin datos
        if ultimo and not datos.get("desglose"):
            filas = sum(v[ultimo[0]] is not None for v in datos["series"].values())
        fig, ax = plt.subplots(figsize=(10, max(4.5 if filas == 1 else 6, 1.2 + 0.66 + filas * FILA_BARRAS)))
        dibujar_ultimo_anio(ax, datos, eje_max, modo)
        sub = f"{datos['unidad']} · {ultimo[1]}" if ultimo else datos["unidad"]
        componer(fig, ax, titulo=titulo, datos=datos, modo=modo, subtitulo=sub, izquierda=0.02 if filas == 1 else 0.2)
        return fig
    if vista == "categorias":
        i = ultimo_indice_comun(datos)
        filas = len(datos.get("categorias") or {}) or 1
        fig, ax = plt.subplots(figsize=(10, max(6, 1.2 + 0.66 + filas * FILA_CATEGORIAS)))
        dibujar_categorias(ax, datos, eje_max, modo)
        sub = datos["unidad"] + (f" · {datos['labels'][i]}, último año con dato de todas las categorías" if i is not None else "")
        componer(fig, ax, titulo=titulo, datos=datos, modo=modo, subtitulo=sub, izquierda=0.24)
        return fig
    if vista == "composicion":
        filas = sum(ultimo_indice_completo(datos, b["id"]) is not None for b in _benchmarks()) if datos.get("composicion") else 1
        partes = len(datos.get("composicion") or {})
        filas_leyenda = -(-partes // 3)  # tres partes por fila
        fig, ax = plt.subplots(figsize=(10, 2.2 + filas * 0.6 + filas_leyenda * 0.28))
        dibujar_composicion(ax, datos, modo)
        claves, etiquetas = ax.get_legend_handles_labels()
        componer(fig, ax, titulo=titulo, datos=datos, modo=modo, subtitulo=f"{datos['unidad']} · último año con dato de cada serie",
                 izquierda=0.2)
        # La leyenda de las partes, en tres columnas debajo de las barras y encima de las fuentes
        alto = fig.get_figheight()
        pie = 0.45 + filas_leyenda * 0.28
        fig.subplots_adjust(bottom=(pie + 0.35) / alto)
        fig.legend(claves, etiquetas, loc="lower left", bbox_to_anchor=(0.015, 0.4 / alto), ncol=3, handlelength=1.2,
                   fontsize=9, labelcolor=_paleta(modo)["texto"], frameon=False)
        return fig
    fig, ax = plt.subplots()
    dibujar_series(ax, datos, modo)
    componer(fig, ax, titulo=titulo, datos=datos, modo=modo)
    return fig


def datos_ccaa(datos: dict) -> dict | None:
    """La vista `ccaa` de unos datos como una gráfica `por_ccaa`, o None si no la tienen (como `vistaCcaa` de
    src/lib/grafica.ts)."""
    v = datos.get("ccaa")
    if not v:
        return None
    return {**v, "id": datos["id"], "tipo": "por_ccaa", "generado_por": datos["generado_por"],
            "generado_en": datos["generado_en"]}


def vista_ccaa(ccaa: dict) -> str:
    """`lineas` si España tiene dato en más de un periodo; si no, `ultimo_anio` (como `vistaDibujoCcaa` de la web)."""
    return "lineas" if sum(v is not None for v in ccaa["series"].get("espana", [])) > 1 else "ultimo_anio"


def figura_ccaa(datos: dict, *, titulo: str, modo: str = "claro"):
    """La vista por comunidades de la gráfica (el selector «Por comunidad» de la web): la evolución de cada
    comunidad y de España, sin benchmarks, o sus barras si la fuente solo da un año. Devuelve la figura para `mostrar`."""
    ccaa = datos_ccaa(datos)
    if ccaa is None:
        raise ValueError("los datos no tienen vista ccaa")
    return figura(ccaa, titulo=titulo, vista=vista_ccaa(ccaa), modo=modo)


def salida(fig) -> dict:
    """Salida `display_data` del notebook con la imagen PNG de `fig` y la huella de los estilos.

    La usan `mostrar` (al ejecutar el notebook) y `python -m ci.notebooks redibujar` (sin ejecutarlo), así
    que las dos dan la misma imagen. Mismos ajustes que el backend `inline` de Jupyter.
    """
    from IPython.core.pylabtools import print_figure

    png = print_figure(fig, "png", bbox_inches="tight")
    ancho, alto = (round(x) for x in fig.get_size_inches() * fig.dpi)
    return {
        "output_type": "display_data",
        "data": {
            "image/png": base64.b64encode(png).decode("ascii"),
            "text/plain": f"<Figure size {ancho}x{alto} with {len(fig.axes)} Axes>",
        },
        "metadata": {"huella_estilos": huella()},
    }


def mostrar(fig) -> None:
    """Muestra la figura en el notebook con la huella de los estilos (ver `huella`) y la cierra."""
    from IPython.display import display

    out = salida(fig)
    plt.close(fig)
    display(out["data"], raw=True, metadata=out["metadata"])
