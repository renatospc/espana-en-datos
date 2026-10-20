"""Fetcher del Ministerio de Vivienda y Agenda Urbana: tablas anuales del Boletín estadístico online.

Portal: https://apps.fomento.gob.es/BoletinOnline2/ (sección «Vivienda»). Cada tabla se publica como un Excel
(`.XLS`, formato BIFF) en `sedal/<código>.XLS`. Mecanismo verificado el 2026-10-20.

Las tablas anuales por comunidades autónomas y provincias tienen, desde la fila de cabecera, una columna por
año (desde 1991) y una fila por territorio: «TOTAL NACIONAL», cada comunidad y, debajo de cada una, sus
provincias. «ND» significa que la comunidad no proporcionó el dato.

- `TABLAS`: `libres_iniciadas` (3.1, viviendas libres iniciadas, estimadas a partir de los proyectos visados
  por los Colegios de Arquitectos) y `protegidas_calificaciones` (1.3, calificaciones provisionales de vivienda
  protegida, planes estatales y autonómicos; hasta 2010 se titulaba «viviendas protegidas iniciadas»).
- `get(tabla, territorios)`: `territorios` mapea el nombre de la fila (como lo escribe el Excel, sin espacios
  sobrantes) al id de serie de la gráfica.

Ejemplo real::

    from lib import mivau

    df, fuentes = mivau.get("libres_iniciadas", {"TOTAL NACIONAL": "espana", "Andalucía": "ES-AN"})
"""

from __future__ import annotations

import io
from datetime import date
from typing import Mapping

import pandas as pd
import requests

from ._http import pedir
from .tipos import FuenteMeta, validar_df

ORGANISMO = "Ministerio de Vivienda y Agenda Urbana"
URL_TABLA = "https://apps.fomento.gob.es/BoletinOnline2/sedal/{codigo}.XLS"
TABLAS = {
    "libres_iniciadas": ("32200500", "viviendas libres iniciadas"),
    "protegidas_calificaciones": ("31303000", "calificaciones provisionales de vivienda protegida"),
}
CABECERA = {"User-Agent": "Mozilla/5.0 (compatible; EspanaenDatos)"}


class MivauError(RuntimeError):
    """Error del Boletín del Ministerio o tabla con un formato no reconocido."""


def parsear_tabla(hoja: pd.DataFrame, codigo: str) -> pd.DataFrame:
    """Filas `territorio, periodo, valor` de una tabla anual leída sin cabecera; «ND» queda en NaN."""
    fila = next(
        (i for i in range(len(hoja)) if pd.to_numeric(hoja.iloc[i, 2], errors="coerce") == 1991), None
    )
    if fila is None:
        raise MivauError(f"{codigo}: no se encuentra la fila de años (que empieza en 1991)")
    años = pd.to_numeric(hoja.iloc[fila, 2:], errors="coerce")
    columnas = [c for c, a in zip(hoja.columns[2:], años) if pd.notna(a)]
    filas = []
    for i in range(fila + 1, len(hoja)):
        nombre = hoja.iloc[i, 1]
        if not isinstance(nombre, str) or nombre.startswith("NOTA") or nombre.startswith("("):
            continue
        for c in columnas:
            filas.append((nombre.strip(), int(hoja.iloc[fila, c]), hoja.iloc[i, c]))
    df = pd.DataFrame(filas, columns=["territorio", "periodo", "valor"])
    df["valor"] = pd.to_numeric(df["valor"].replace("ND", None), errors="coerce")
    return df


def get(
    tabla: str,
    territorios: Mapping[str, str],
    *,
    desde: int = 1976,
    fecha_consulta: str | None = None,
    sesion: requests.Session | None = None,
    reintentos: int = 2,
) -> tuple[pd.DataFrame, list[FuenteMeta]]:
    """Descarga una tabla anual por comunidades. Devuelve `(DataFrame serie/periodo/valor, fuentes)`."""
    if tabla not in TABLAS:
        raise ValueError(f"tabla {tabla!r} no válida; usa {', '.join(TABLAS)}")
    codigo, nombre = TABLAS[tabla]
    url = URL_TABLA.format(codigo=codigo)
    r = pedir(
        sesion or requests.Session(), url, None,
        error_cls=MivauError, etiqueta=codigo, mensaje=lambda r: r.text[:200], headers=CABECERA, reintentos=reintentos,
    )
    try:
        hoja = pd.read_excel(io.BytesIO(r.content), header=None)
    except Exception as e:  # xlrd lanza varios tipos según el fallo
        raise MivauError(f"{codigo}: no es un Excel legible") from e
    obs = parsear_tabla(hoja, codigo)
    faltan = [t for t in territorios if t not in set(obs["territorio"])]
    if faltan:
        raise MivauError(f"{codigo}: faltan los territorios {faltan}")
    obs = obs[obs["territorio"].isin(territorios) & (obs["periodo"] >= desde)]
    df = validar_df(pd.DataFrame({
        "serie": obs["territorio"].map(territorios), "periodo": obs["periodo"].astype("int64"), "valor": obs["valor"],
    }).dropna(subset=["valor"]))
    hoy = fecha_consulta or date.today().isoformat()
    fuentes = [
        FuenteMeta(s, ORGANISMO, f"Boletín estadístico online, tabla {codigo} ({nombre})", url, hoy)
        for s in df["serie"].unique()
    ]
    return df, fuentes
