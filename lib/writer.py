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
from .tipos import FuenteMeta, validar_df

RAIZ = Path(__file__).resolve().parent.parent
GLOBAL = RAIZ / "global.json"
ESQUEMA = RAIZ / "schemas" / "grafica-data.schema.json"

TIPOS = ("serie_temporal", "por_ccaa", "solo_espana")

# En las notas, un grupo con al menos tantas comunidades (la mayoría de las 19) se llama «comunidades autónomas».
MIN_CCAA_AGRUPADAS = 10


def _benchmarks() -> list[dict]:
    return json.loads(GLOBAL.read_text(encoding="utf-8"))["benchmarks"]


def _orden_series(tipo: str, claves: set[str], benchmarks: list[str]) -> list[str]:
    """Comprueba las claves según `tipo` y devuelve el orden estable de salida."""
    if tipo == "serie_temporal":
        esperadas = set(benchmarks)
        etiqueta = "serie_temporal (cesta de benchmarks)"
    elif tipo == "solo_espana":
        esperadas = {"espana"}
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
    faltan, sobran = esperadas - claves, claves - esperadas
    if faltan or sobran:
        raise ValueError(
            f"claves de series incorrectas para {etiqueta}"
            + (f"; faltan: {', '.join(sorted(faltan))}" if faltan else "")
            + (f"; sobran: {', '.join(sorted(sobran))}" if sobran else "")
        )
    return [b for b in benchmarks if b in esperadas] if tipo == "serie_temporal" else ["espana"]


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
) -> dict:
    """Construye y valida el diccionario de `data/<id>.json` (sin escribirlo)."""
    df = validar_df(df)
    df = df[df["periodo"] >= desde]  # la ventana empieza en `desde` (METODOLOGIA §2.3)
    if df["valor"].notna().sum() == 0:
        raise ValueError("no hay ningún dato en la ventana temporal")
    hasta = int(df.loc[df["valor"].notna(), "periodo"].max())
    años = list(range(desde, hasta + 1))
    labels = [str(a) for a in años]

    benchmarks = _benchmarks()
    series_orden = _orden_series(tipo, set(df["serie"]), [b["id"] for b in benchmarks])
    series: dict[str, list[float | None]] = {}
    for s in series_orden:
        por_año = df[df["serie"] == s].set_index("periodo")["valor"]
        series[s] = [
            None if a not in por_año.index or pd.isna(por_año[a]) else float(por_año[a])
            for a in años
        ]
    nombres = {**NOMBRES_CCAA, **{b["id"]: b["nombre"] for b in benchmarks}}
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
        "labels": labels,
        "series": series,
        "fuentes": [por_serie[s].to_dict() for s in series],
        "notas": [*notas, *notas_auto],
        "generado_por": generado_por,
        "generado_en": generado_en
        or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
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
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(datos, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    csv = csv_grafica(datos, formato=csv_formato, decimales=csv_decimales)
    path.with_suffix(".csv").write_text(csv, encoding="utf-8", newline="")
    return path
