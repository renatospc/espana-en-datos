"""Fetcher de la OCDE (OECD Data Explorer, SDMX REST, formato SDMX-CSV).

Documentación: https://gitlab.algobank.oecd.org/public-documentation/dotstatsuite-documentation/-/blob/master/content/en/api/sdmx-rest/_index.md
(resumen: https://www.oecd.org/en/data/insights/data-explainers/2024/09/api.html)

Ejemplo real (PIB real per cápita en USD PPA, "National Accounts at a Glance")::

    from lib import oecd

    df, fuentes = oecd.get(
        "OECD.SDD.NAD,DSD_NAAG@DF_NAAG_I,1.0",
        "A.{AREA}.B1GQ_R.USD_PPP.NAAG_I",
        areas={"ESP": "espana", "USA": "eeuu", "CAN": "canada", "OECD": "ocde"},
    )

`dataflow` es `AGENCIA,ID,VERSION` (se copia de «Developer API» en el Data Explorer).
`clave` es la clave SDMX con el marcador `{AREA}` en la dimensión de país (se sustituye
por los códigos de `areas` unidos con `+`). Las dimensiones deben quedar fijadas de modo
que haya una sola observación por (área, año); si no, `ValueError`. Solo periodos anuales.
La API devuelve todo en una respuesta (sin paginación). Las áreas sin datos no aparecen
en el resultado ni en `fuentes`.
"""

from __future__ import annotations

import io
from datetime import date
from typing import Mapping

import pandas as pd
import requests

from ._http import pedir
from .tipos import COLUMNAS, FuenteMeta, validar_df

BASE = "https://sdmx.oecd.org/public/rest/data"
URL_EXPLORER = "https://data-explorer.oecd.org/"
ORGANISMO = "OECD"
CABECERA_CSV = {"Accept": "application/vnd.sdmx.data+csv;version=1.0.0"}
AREAS_POR_DEFECTO = {"ESP": "espana", "USA": "eeuu", "CAN": "canada", "OECD": "ocde"}


class OecdError(RuntimeError):
    """Error devuelto por el servicio SDMX de la OCDE o fallo de red persistente."""


def csv_a_df(texto: str, areas: Mapping[str, str], etiqueta: str = "") -> pd.DataFrame:
    """Convierte SDMX-CSV al DataFrame estándar `serie, periodo, valor`."""
    if not texto.strip():
        raise OecdError(f"{etiqueta}: respuesta vacía")
    raw = pd.read_csv(io.StringIO(texto), dtype=str)
    for col in ("REF_AREA", "TIME_PERIOD", "OBS_VALUE"):
        if col not in raw.columns:
            raise OecdError(f"{etiqueta}: la respuesta no es SDMX-CSV (falta {col})")
    raw = raw[raw["REF_AREA"].isin(areas)]
    if not raw["TIME_PERIOD"].str.fullmatch(r"\d{4}").all():
        raise ValueError(f"{etiqueta}: periodo no anual; solo se admiten años")
    dup = raw.duplicated(["REF_AREA", "TIME_PERIOD"], keep=False)
    if dup.any():
        sobran = [c for c in raw.columns if c not in COLUMNAS and raw.loc[dup, c].nunique() > 1]
        raise ValueError(
            f"{etiqueta}: varias observaciones por (área, año); fija en `clave` las dimensiones: "
            + ", ".join(sobran)
        )
    df = pd.DataFrame(
        {
            "serie": raw["REF_AREA"].map(areas),
            "periodo": raw["TIME_PERIOD"].astype(int),
            "valor": pd.to_numeric(raw["OBS_VALUE"]),
        }
    )[COLUMNAS].dropna(subset=["valor"])
    return validar_df(df)


def get(
    dataflow: str,
    clave: str,
    *,
    areas: Mapping[str, str] | None = None,
    desde: int = 1976,
    fecha_consulta: str | None = None,
    sesion: requests.Session | None = None,
    reintentos: int = 2,
) -> tuple[pd.DataFrame, list[FuenteMeta]]:
    """Descarga datos anuales de la OCDE. Devuelve `(DataFrame serie/periodo/valor, fuentes)`.

    `areas`: código de área OCDE → id de serie (por defecto ESP, USA, CAN, OECD).
    """
    areas = dict(areas or AREAS_POR_DEFECTO)
    if "{AREA}" not in clave:
        raise ValueError("`clave` debe contener el marcador {AREA}")
    ruta = clave.replace("{AREA}", "+".join(areas))
    etiqueta = dataflow.split(",")[1] if "," in dataflow else dataflow
    r = pedir(
        sesion or requests.Session(),
        f"{BASE}/{dataflow}/{ruta}",
        {"startPeriod": str(desde)},
        error_cls=OecdError,
        etiqueta=etiqueta,
        mensaje=lambda r: r.text[:200],
        headers=CABECERA_CSV,
        reintentos=reintentos,
    )
    df = csv_a_df(r.text, areas, etiqueta)
    hoy = fecha_consulta or date.today().isoformat()
    fuentes = [FuenteMeta(s, ORGANISMO, etiqueta, URL_EXPLORER, hoy) for s in df["serie"].unique()]
    return df, fuentes
