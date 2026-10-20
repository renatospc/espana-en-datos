"""Escritor único de `temas/<slug>/data/<id>.json` y de su copia en CSV `<id>.csv` (TAD §2.1, §3)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Sequence

import jsonschema
import pandas as pd

from .ccaa import CODIGOS_CCAA, NOMBRES_CCAA
from .paises import GRUPOS_PAISES, NOMBRES_AGREGADOS, nombre_punto, paises_de
from .tipos import FuenteMeta, validar_df

RAIZ = Path(__file__).resolve().parent.parent
GLOBAL = RAIZ / "global.json"
ESQUEMA = RAIZ / "schemas" / "grafica-data.schema.json"

TIPOS = ("serie_temporal", "por_ccaa", "solo_espana")

# En las notas, un grupo con al menos tantas comunidades (la mayoría de las 19) se llama «comunidades autónomas».
MIN_CCAA_AGRUPADAS = 10


def _benchmarks() -> list[dict]:
    return json.loads(GLOBAL.read_text(encoding="utf-8"))["benchmarks"]


def _orden_series(
    tipo: str,
    claves: set[str],
    benchmarks: list[str],
    desglose: Sequence[str] = (),
    categorias: Sequence[str] = (),
    composicion: Sequence[str] = (),
) -> list[str]:
    """Comprueba las claves según `tipo` y devuelve el orden estable de salida."""
    if desglose and tipo != "solo_espana":
        raise ValueError("el desglose solo vale en solo_espana")
    if categorias and (tipo != "solo_espana" or desglose or "espana" in categorias):
        raise ValueError(
            'las categorías solo valen en solo_espana, sin desglose y sin "espana"'
        )
    if composicion and tipo != "serie_temporal":
        raise ValueError("la composición solo vale en serie_temporal")
    if tipo == "serie_temporal" and composicion:
        orden = [f"{b}__{k}" for b in benchmarks for k in composicion]
        etiqueta = "serie_temporal con composición (<benchmark>__<parte>)"
    elif tipo == "serie_temporal":
        orden = list(benchmarks)
        etiqueta = "serie_temporal (cesta de benchmarks)"
    elif tipo == "solo_espana":
        orden = list(categorias) or ["espana", *desglose]
        etiqueta = "solo_espana"
    elif tipo == "por_ccaa":
        sobran = claves - {"espana", *CODIGOS_CCAA}
        if sobran or "espana" not in claves or len(claves) < 2:
            raise ValueError(
                'por_ccaa requiere "espana" y códigos CCAA (ISO 3166-2:ES)'
                + (f"; claves no válidas: {', '.join(sorted(sobran))}" if sobran else "")
            )
        return ["espana", *sorted(claves - {"espana"})]
    else:
        raise ValueError(f"tipo desconocido: {tipo!r}; válidos: {', '.join(TIPOS)}")
    esperadas = set(orden)
    faltan, sobran = esperadas - claves, claves - esperadas
    if faltan or sobran:
        raise ValueError(
            f"claves de series incorrectas para {etiqueta}"
            + (f"; faltan: {', '.join(sorted(faltan))}" if faltan else "")
            + (f"; sobran: {', '.join(sorted(sobran))}" if sobran else "")
        )
    return orden


def _unir(nombres: Sequence[str]) -> str:
    """«A», «A y B», «A, B y C»."""
    return nombres[0] if len(nombres) == 1 else f"{', '.join(nombres[:-1])} y {nombres[-1]}"


def _notas_automaticas(
    series: dict[str, list[float | None]], nombres: dict[str, str], tipo: str, años: list[int]
) -> list[str]:
    """Primer año con dato de cada serie (METODOLOGIA §2.3), con los nombres que ve el lector.

    Una nota por año (o por «sin datos»), con las series que comparten ese año. En `por_ccaa`, las
    comunidades van por orden alfabético; si son al menos `MIN_CCAA_AGRUPADAS`, se escribe
    «comunidades autónomas», con «salvo …» para las de la gráfica que tienen otra nota.
    """
    grupos: dict[str, list[str]] = {}
    for s, valores in series.items():
        primero = next((a for a, v in zip(años, valores) if v is not None), None)
        estado = (
            f"primer dato disponible en {primero}"
            if primero is not None
            else f"sin datos en la ventana {años[0]}-{años[-1]}"
        )
        grupos.setdefault(estado, []).append(s)
    ccaa = [s for s in series if s != "espana"] if tipo == "por_ccaa" else []
    notas = []
    for estado, claves in grupos.items():
        dentro = [k for k in claves if k in ccaa]
        fuera = [k for k in ccaa if k not in claves]
        if len(dentro) >= MIN_CCAA_AGRUPADAS:
            salvo = f" salvo {_unir(sorted(nombres[k] for k in fuera))}" if fuera else ""
            comunidades = [f"comunidades autónomas{salvo}"]
        else:
            comunidades = sorted(nombres[k] for k in dentro)
        texto = _unir([nombres[k] for k in claves if k not in ccaa] + comunidades)
        notas.append(f"{texto[0].upper()}{texto[1:]}: {estado}.")
    return notas


def _validar_esquema(datos: dict) -> None:
    esquema = json.loads(ESQUEMA.read_text(encoding="utf-8"))
    validador = jsonschema.Draft202012Validator(
        esquema, format_checker=jsonschema.FormatChecker()
    )
    errores = sorted(validador.iter_errors(datos), key=lambda e: list(e.absolute_path))
    if errores:
        raise ValueError(
            "no cumple grafica-data.schema.json:\n"
            + "\n".join(
                f"  {'.'.join(map(str, e.absolute_path)) or '(raíz)'}: {e.message}"
                for e in errores
            )
        )


def construir_vista_ccaa(
    df: pd.DataFrame,
    fuentes: Sequence[FuenteMeta],
    *,
    unidad: str,
    notas: Sequence[str],
    desde: int = 1976,
    referencia: float | None = None,
) -> dict:
    """Vista `ccaa` de una gráfica de España (METODOLOGIA §2.7), para el parámetro `ccaa` de `construir_grafica_data`.

    `df` es un DataFrame estándar con la serie `espana` (el total de España de la fuente regional) y una
    serie por código ISO 3166-2:ES. Igual que una gráfica `por_ccaa`: periodos anuales desde `desde`
    hasta el último con algún dato, huecos en `null`, `fuentes` una por serie y, tras las `notas` del
    notebook, las automáticas con el primer año con dato. `referencia`: línea horizontal (p. ej. 100).
    """
    d = construir_grafica_data(
        df, fuentes, id="vista-ccaa", tipo="por_ccaa", unidad=unidad, notas=notas, generado_por="",
        desde=desde, referencia=referencia, generado_en="2000-01-01T00:00:00Z",
    )
    return {k: d[k] for k in ("unidad", "referencia", "labels", "series", "fuentes", "notas") if k in d}


def construir_grafica_data(
    df: pd.DataFrame,
    fuentes: Sequence[FuenteMeta],
    *,
    id: str,
    tipo: str,
    unidad: str,
    notas: Sequence[str],
    generado_por: str,
    desde: int = 1976,
    generado_en: str | None = None,
    referencia: float | None = None,
    desglose: dict[str, str] | None = None,
    categorias: dict[str, str] | None = None,
    proyeccion: dict[str, dict[str, str]] | None = None,
    composicion: dict[str, str] | None = None,
    ccaa: dict | None = None,
) -> dict:
    """Construye y valida el diccionario de `data/<id>.json` (sin escribirlo).

    `referencia` es el valor de una línea horizontal de referencia (p. ej. 100 en un índice), que
    dibujan los notebooks, la web y la imagen descargable; sin ella, el JSON no lleva el campo.
    `desglose` (solo en `solo_espana`) nombra las partes de la serie `espana`, como
    {clave: nombre}: cada clave es una serie más del DataFrame, con su fuente.
    `categorias` (solo en `solo_espana`, sin `desglose`) nombra categorías que no son partes de un
    total, como {clave: nombre}: cada clave es una serie, con su fuente, y no hay serie `espana`.
    `proyeccion` marca las series con años proyectados, como {serie: {"desde": "2030", "edicion":
    "OCDE, Pensions at a Glance 2023"}}: `desde` es el primer periodo proyectado.
    `composicion` (solo en `serie_temporal`) nombra las partes en que se reparte cada serie de la cesta,
    como {clave: nombre}: las series del DataFrame son `<benchmark>__<clave>`, cada una con su fuente.
    `ccaa` es la vista por comunidades (solo en `serie_temporal` sin `composicion` y en `solo_espana`),
    construida con `construir_vista_ccaa`.
    """
    if ccaa and (tipo not in ("serie_temporal", "solo_espana") or composicion):
        raise ValueError("la vista ccaa solo vale en serie_temporal (sin composición) y solo_espana")
    desglose = desglose or {}
    composicion = composicion or {}
    categorias = categorias or {}
    df = validar_df(df)
    df = df[df["periodo"] >= desde]  # la ventana empieza en `desde` (METODOLOGIA §2.3)
    if df["valor"].notna().sum() == 0:
        raise ValueError("no hay ningún dato en la ventana temporal")
    hasta = int(df.loc[df["valor"].notna(), "periodo"].max())
    años = list(range(desde, hasta + 1))
    labels = [str(a) for a in años]

    benchmarks = _benchmarks()
    series_orden = _orden_series(
        tipo, set(df["serie"]), [b["id"] for b in benchmarks], list(desglose), list(categorias), list(composicion)
    )
    series: dict[str, list[float | None]] = {}
    for s in series_orden:
        por_año = df[df["serie"] == s].set_index("periodo")["valor"]
        series[s] = [
            None if a not in por_año.index or pd.isna(por_año[a]) else float(por_año[a])
            for a in años
        ]
    nombres = {**NOMBRES_CCAA, **{b["id"]: b["nombre"] for b in benchmarks}, **desglose, **categorias}
    if composicion:
        # Primer año con dato de cada benchmark: el primero con todas sus partes
        completas = {
            b["id"]: [None if any(series[f"{b['id']}__{k}"][i] is None for k in composicion) else 1.0
                      for i in range(len(años))]
            for b in benchmarks
        }
        notas_auto = _notas_automaticas(completas, nombres, tipo, años)
    else:
        notas_auto = _notas_automaticas(series, nombres, tipo, años)

    por_serie = {f.serie: f for f in fuentes}
    if len(por_serie) != len(fuentes):
        raise ValueError("hay series con fuentes duplicadas")
    ajenas = set(por_serie) - set(series)
    if ajenas:
        raise ValueError(f"fuentes de series inexistentes: {', '.join(sorted(ajenas))}")
    sin_fuente = [s for s in series if s not in por_serie]
    if sin_fuente:
        raise ValueError(f"series sin fuente: {', '.join(sin_fuente)}")

    datos = {
        "id": id,
        "tipo": tipo,
        "unidad": unidad,
        **({} if referencia is None else {"referencia": referencia}),
        **({"desglose": dict(desglose)} if desglose else {}),
        **({"categorias": dict(categorias)} if categorias else {}),
        **({"composicion": dict(composicion)} if composicion else {}),
        **({"proyeccion": proyeccion} if proyeccion else {}),
        "labels": labels,
        "series": series,
        "fuentes": [por_serie[s].to_dict() for s in series],
        "notas": [*notas, *notas_auto],
        **({"ccaa": ccaa} if ccaa else {}),
        "generado_por": generado_por,
        "generado_en": generado_en
        or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _validar_esquema(datos)
    return datos


# Formatos de CSV: separador y marca decimal (como `FormatoCsv` de src/lib/descargas.ts).
FORMATOS_CSV = {"es": (";", ","), "int": (",", ".")}


def _numero(v: float, decimales: int, coma: str) -> str:
    """Igual que `v.toFixed(decimales)` en JavaScript (mitad hacia arriba sobre el valor binario exacto)."""
    v = float(v)
    if v == 0:
        v = 0.0  # toFixed no escribe el signo de -0
    texto = f"{Decimal(v).quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_UP):f}"
    return texto.replace(".", coma)


def csv_grafica(datos: dict, *, formato: str = "es", decimales: int = 2) -> str:
    """CSV de la gráfica, idéntico a `csvDescarga` de src/lib/descargas.ts (lo comprueba `pnpm validate`).

    UTF-8 con BOM y saltos CRLF. `formato` = `es` (separador `;` y coma decimal, para Excel en español)
    o `int` (separador `,` y punto decimal); `decimales` redondea los valores (el JSON conserva el valor
    completo). Columnas: `periodo` + ids de series; un hueco (`null`) es una celda vacía.
    """
    if formato not in FORMATOS_CSV:
        raise ValueError(f"formato de CSV desconocido: {formato!r}; válidos: {', '.join(FORMATOS_CSV)}")
    if not isinstance(decimales, int) or not 0 <= decimales <= 10:
        raise ValueError(f"decimales del CSV debe ser un entero entre 0 y 10, no {decimales!r}")
    sep, coma = FORMATOS_CSV[formato]

    def campo(texto: str) -> str:
        return '"' + texto.replace('"', '""') + '"' if any(c in texto for c in f'"{sep}\r\n') else texto

    claves = list(datos["series"])
    filas = [sep.join(campo(c) for c in ["periodo", *claves])]
    for i, label in enumerate(datos["labels"]):
        valores = ["" if (v := datos["series"][k][i]) is None else _numero(v, decimales, coma) for k in claves]
        filas.append(sep.join(campo(c) for c in [label, *valores]))
    return "\ufeff" + "\r\n".join(filas) + "\r\n"


def write_grafica_data(
    df: pd.DataFrame,
    fuentes: Sequence[FuenteMeta],
    *,
    id: str,
    tipo: str,
    unidad: str,
    notas: Sequence[str],
    generado_por: str,
    desde: int = 1976,
    path: str | Path,
    generado_en: str | None = None,
    referencia: float | None = None,
    desglose: dict[str, str] | None = None,
    categorias: dict[str, str] | None = None,
    proyeccion: dict[str, dict[str, str]] | None = None,
    composicion: dict[str, str] | None = None,
    ccaa: dict | None = None,
    csv_formato: str = "es",
    csv_decimales: int = 2,
) -> Path:
    """Escribe `data/<id>.json` validado y, al lado, `data/<id>.csv` (ver `csv_grafica`). El JSON debe llamarse `<id>.json`."""
    path = Path(path)
    if path.name != f"{id}.json":
        raise ValueError(f"el fichero debe llamarse {id}.json, no {path.name}")
    datos = construir_grafica_data(
        df,
        fuentes,
        id=id,
        tipo=tipo,
        unidad=unidad,
        notas=notas,
        generado_por=generado_por,
        desde=desde,
        generado_en=generado_en,
        referencia=referencia,
        desglose=desglose,
        categorias=categorias,
        proyeccion=proyeccion,
        composicion=composicion,
        ccaa=ccaa,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(datos, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    csv = csv_grafica(datos, formato=csv_formato, decimales=csv_decimales)
    path.with_suffix(".csv").write_text(csv, encoding="utf-8", newline="")
    return path


# ---------- Dispersión (METODOLOGIA §2.6) ----------

NOTA_CAUSALIDAD = "La relación entre dos indicadores no muestra que uno cause el otro."
EJES = ("eje_x", "eje_y")


def _periodo(años: Sequence[int]) -> str:
    """Intervalo de años de los puntos de un eje: «2023» o «2019-2023»."""
    a, b = min(años), max(años)
    return str(a) if a == b else f"{a}-{b}"


def _por_codigo(df: pd.DataFrame, nombre: str, desde: int, anios: tuple[int, int] | None) -> pd.Series:
    """Serie (código, año) → valor sin huecos, dentro de la ventana."""
    df = validar_df(df)
    df = df[(df["periodo"] >= desde) & df["valor"].notna()]
    if anios is not None:
        df = df[df["periodo"].between(*anios)]
    if df.empty:
        raise ValueError(f"{nombre}: no hay ningún dato en la ventana temporal")
    return df.set_index(["serie", "periodo"])["valor"]


def construir_dispersion_data(
    x: pd.DataFrame,
    y: pd.DataFrame,
    fuentes: Sequence[FuenteMeta],
    *,
    id: str,
    universo: str,
    eje_x: dict,
    eje_y: dict,
    notas: Sequence[str],
    generado_por: str,
    desde: int = 1976,
    anios: tuple[int, int] | None = None,
    generado_en: str | None = None,
) -> dict:
    """Construye y valida el `data/<id>.json` de una gráfica `dispersion` (sin escribirlo).

    `x` e `y` son DataFrames estándar (`serie, periodo, valor`) con una serie por código de país
    (ISO 3166-1 alfa-3 de `paises`) o de agregado (`codigo_iso` de un benchmark, p. ej. OECD) y
    periodos anuales. Cada punto usa el último año en que el país tiene dato en los dos ejes, el
    mismo para `x` e `y` (METODOLOGIA §2.6); `anios` = (desde, hasta) limita los años candidatos
    si el notebook fija una ventana. `eje_x` y `eje_y` son `{"titulo": ..., "unidad": ...}`: el
    `periodo` de cada eje se calcula con los años de los puntos. `fuentes` lleva `serie` = "eje_x"
    o "eje_y" (al menos una por eje). Las notas añaden los países del universo sin dato en los dos
    ejes y la advertencia de que la relación no muestra causa.
    """
    del_universo = paises_de(universo)
    vx = _por_codigo(x, "eje x", desde, anios)
    vy = _por_codigo(y, "eje y", desde, anios)
    validos = set(del_universo) | set(NOMBRES_AGREGADOS)
    ajenos = (set(vx.index.get_level_values(0)) | set(vy.index.get_level_values(0))) - validos
    if ajenos:
        fuera = sorted(c for c in ajenos if c in GRUPOS_PAISES)
        raise ValueError(
            f"códigos que no son de {universo} ni agregados de benchmarks: {', '.join(sorted(ajenos))}"
            + (f" (países de otro universo: {', '.join(fuera)})" if fuera else "")
        )
    comunes = vx.index.intersection(vy.index)
    puntos = []
    for codigo in [*del_universo, *NOMBRES_AGREGADOS]:
        años = [a for c, a in comunes if c == codigo]
        if años:
            a = max(años)
            puntos.append(
                {"codigo": codigo, "anio": int(a), "x": float(vx[(codigo, a)]), "y": float(vy[(codigo, a)])}
            )
    con_punto = {p["codigo"] for p in puntos}
    if "ESP" not in con_punto:
        raise ValueError("España (ESP) no tiene dato en los dos ejes el mismo año")

    por_eje = {e: [f for f in fuentes if f.serie == e] for e in EJES}
    otras = [f.serie for f in fuentes if f.serie not in EJES]
    if otras:
        raise ValueError(f'en dispersion, la serie de cada fuente es "eje_x" o "eje_y" (no {", ".join(otras)})')
    sin_fuente = [e for e in EJES if not por_eje[e]]
    if sin_fuente:
        raise ValueError(f"falta la fuente de {', '.join(sin_fuente)}")

    años_puntos = [p["anio"] for p in puntos]
    sin_dato = [nombre_punto(c) for c in del_universo if c not in con_punto]
    notas_auto = []
    if sin_dato:
        notas_auto.append(
            f"Sin dato en los dos ejes el mismo año ({len(sin_dato)} de los {len(del_universo)} países): "
            f"{_unir(sorted(sin_dato))}."
        )
    notas_auto.append(NOTA_CAUSALIDAD)

    datos = {
        "id": id,
        "tipo": "dispersion",
        "universo": universo,
        "eje_x": {"titulo": eje_x["titulo"], "unidad": eje_x["unidad"], "periodo": _periodo(años_puntos)},
        "eje_y": {"titulo": eje_y["titulo"], "unidad": eje_y["unidad"], "periodo": _periodo(años_puntos)},
        "puntos": puntos,
        "fuentes": [f.to_dict() for e in EJES for f in por_eje[e]],
        "notas": [*notas, *notas_auto],
        "generado_por": generado_por,
        "generado_en": generado_en
        or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _validar_esquema(datos)
    return datos


def csv_dispersion(datos: dict, *, formato: str = "es", decimales: int = 2) -> str:
    """CSV de una dispersión, idéntico a `csvDescarga` de src/lib/descargas.ts: `codigo;pais;anio;eje_x;eje_y`."""
    if formato not in FORMATOS_CSV:
        raise ValueError(f"formato de CSV desconocido: {formato!r}; válidos: {', '.join(FORMATOS_CSV)}")
    if not isinstance(decimales, int) or not 0 <= decimales <= 10:
        raise ValueError(f"decimales del CSV debe ser un entero entre 0 y 10, no {decimales!r}")
    sep, coma = FORMATOS_CSV[formato]

    def campo(texto: str) -> str:
        return '"' + texto.replace('"', '""') + '"' if any(c in texto for c in f'"{sep}\r\n') else texto

    filas = [sep.join(["codigo", "pais", "anio", "eje_x", "eje_y"])]
    for p in datos["puntos"]:
        celdas = [
            p["codigo"], nombre_punto(p["codigo"]), str(p["anio"]),
            _numero(p["x"], decimales, coma), _numero(p["y"], decimales, coma),
        ]
        filas.append(sep.join(campo(c) for c in celdas))
    return "﻿" + "\r\n".join(filas) + "\r\n"


def write_dispersion_data(
    x: pd.DataFrame,
    y: pd.DataFrame,
    fuentes: Sequence[FuenteMeta],
    *,
    id: str,
    universo: str,
    eje_x: dict,
    eje_y: dict,
    notas: Sequence[str],
    generado_por: str,
    path: str | Path,
    desde: int = 1976,
    anios: tuple[int, int] | None = None,
    generado_en: str | None = None,
    csv_formato: str = "es",
    csv_decimales: int = 2,
) -> Path:
    """Escribe `data/<id>.json` de una dispersión, validado, y al lado `data/<id>.csv` (ver `csv_dispersion`)."""
    path = Path(path)
    if path.name != f"{id}.json":
        raise ValueError(f"el fichero debe llamarse {id}.json, no {path.name}")
    datos = construir_dispersion_data(
        x, y, fuentes, id=id, universo=universo, eje_x=eje_x, eje_y=eje_y, notas=notas,
        generado_por=generado_por, desde=desde, anios=anios, generado_en=generado_en,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(datos, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    csv = csv_dispersion(datos, formato=csv_formato, decimales=csv_decimales)
    path.with_suffix(".csv").write_text(csv, encoding="utf-8", newline="")
    return path
