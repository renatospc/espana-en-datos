"""Escritor único de `temas/<slug>/data/<id>.json` y de su copia en CSV `<id>.csv` (TAD §2.1, §3)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import jsonschema
import numpy as np
import pandas as pd

from .tipos import FuenteMeta, validar_df

RAIZ = Path(__file__).resolve().parent.parent
GLOBAL = RAIZ / "global.json"
ESQUEMA = RAIZ / "schemas" / "grafica-data.schema.json"

TIPOS = ("serie_temporal", "por_ccaa", "solo_espana")

# Debe coincidir con CODIGOS_CCAA de src/lib/schema.ts (lo comprueba tests/test_writer.py).
CODIGOS_CCAA = (
    "ES-AN ES-AR ES-AS ES-CB ES-CE ES-CL ES-CM ES-CN ES-CT ES-EX "
    "ES-GA ES-IB ES-MC ES-MD ES-ML ES-NC ES-PV ES-RI ES-VC"
).split()


def _benchmarks() -> list[str]:
    return [b["id"] for b in json.loads(GLOBAL.read_text(encoding="utf-8"))["benchmarks"]]


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

    series_orden = _orden_series(tipo, set(df["serie"]), _benchmarks())
    series: dict[str, list[float | None]] = {}
    notas_auto: list[str] = []
    for s in series_orden:
        por_año = df[df["serie"] == s].set_index("periodo")["valor"]
        series[s] = [
            None if a not in por_año.index or pd.isna(por_año[a]) else float(por_año[a])
            for a in años
        ]
        primero = next((a for a, v in zip(años, series[s]) if v is not None), None)
        notas_auto.append(
            f"{s}: primer dato disponible en {primero}."
            if primero is not None
            else f"{s}: sin datos en la ventana {desde}-{hasta}."
        )

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


def _numero(v: float) -> str:
    """Igual que `String(v)` en JavaScript para los valores de una gráfica (100 → "100", 1.5 → "1.5")."""
    v = float(v)
    if v.is_integer() and abs(v) < 1e21:
        return str(int(v))
    texto = repr(v)
    if "e" in texto and 1e-7 <= abs(v) < 1e21:  # JavaScript no usa exponente en este rango
        texto = np.format_float_positional(v, trim="-")
    return re.sub(r"e([+-])0(\d)$", r"e\1\2", texto)  # 1e-08 → 1e-8, como JavaScript


def _campo(texto: str) -> str:
    return '"' + texto.replace('"', '""') + '"' if any(c in texto for c in '",\r\n') else texto


def csv_grafica(datos: dict) -> str:
    """CSV de la gráfica, idéntico a `csvDescarga` de src/lib/descargas.ts (lo comprueba `pnpm validate`).

    UTF-8 con BOM, separador coma, punto decimal y saltos CRLF. Columnas: `periodo` + ids de series;
    un hueco (`null`) es una celda vacía.
    """
    claves = list(datos["series"])
    filas = [",".join(_campo(c) for c in ["periodo", *claves])]
    for i, label in enumerate(datos["labels"]):
        valores = ["" if (v := datos["series"][k][i]) is None else _numero(v) for k in claves]
        filas.append(",".join(_campo(c) for c in [label, *valores]))
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
) -> Path:
    """Escribe `data/<id>.json` validado y, al lado, `data/<id>.csv`. El JSON debe llamarse `<id>.json`."""
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
    path.with_suffix(".csv").write_text(csv_grafica(datos), encoding="utf-8", newline="")
    return path
