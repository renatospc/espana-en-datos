"""Fetcher del Banco Mundial (World Bank API v2).

Documentación: https://datahelpdesk.worldbank.org/knowledgebase/articles/889392-about-the-indicators-api-documentation

Ejemplo real (desempleo, % de la población activa, estimación modelada OIT)::

    from lib import worldbank

    df, fuentes = worldbank.get(
        "SL.UEM.TOTL.ZS",
        paises={"ESP": "espana", "EUU": "ue27", "OED": "ocde", "USA": "eeuu", "CAN": "canada"},
    )

`paises` mapea el código ISO3 (o de agregado: `EUU` = Unión Europea, `OED` = miembros OCDE)
al id de serie. La API pagina (`per_page`/`page`); `get` recorre todas las páginas.
Los valores nulos de la API se omiten; los países sin datos no aparecen en el resultado.
"""

from __future__ import annotations

from datetime import date
from typing import Mapping

import pandas as pd
import requests

from ._http import pedir
from .tipos import COLUMNAS, FuenteMeta, validar_df

BASE = "https://api.worldbank.org/v2"
URL_INDICADOR = "https://data.worldbank.org/indicator/{indicador}"
ORGANISMO = "World Bank"
PAISES_POR_DEFECTO = {"ESP": "espana", "EUU": "ue27", "OED": "ocde", "USA": "eeuu", "CAN": "canada"}
POR_PAGINA = 1000


class WorldBankError(RuntimeError):
    """Error devuelto por la API del Banco Mundial o fallo de red persistente."""


def _mensaje(r: requests.Response) -> str:
    try:
        return "; ".join(m.get("value", "") for m in r.json()[0]["message"])
    except (ValueError, KeyError, IndexError, TypeError):
        return r.text[:200]


def parsear_pagina(js: object, indicador: str = "") -> tuple[dict, list[dict]]:
    """Devuelve `(meta de paginación, registros)`; lanza `WorldBankError` si es un error de la API.

    El Banco Mundial responde con HTTP 200 incluso para errores (`[{"message": [...]}]`).
    """
    if not isinstance(js, list) or not js or not isinstance(js[0], dict):
        raise WorldBankError(f"{indicador}: respuesta no reconocida")
    if "message" in js[0]:
        detalle = "; ".join(f"{m.get('key')}: {m.get('value')}" for m in js[0]["message"])
        raise WorldBankError(f"{indicador}: error de la API: {detalle}")
    return js[0], ((js[1] or []) if len(js) > 1 else [])


def registros_a_df(registros: list[dict], paises: Mapping[str, str]) -> pd.DataFrame:
    filas = [
        (paises[x["countryiso3code"]], int(x["date"]), float(x["value"]))
        for x in registros
        if x.get("value") is not None and x.get("countryiso3code") in paises
    ]
    return validar_df(pd.DataFrame(filas, columns=COLUMNAS))


def get(
    indicador: str,
    *,
    paises: Mapping[str, str] | None = None,
    desde: int = 1976,
    hasta: int | None = None,
    fecha_consulta: str | None = None,
    sesion: requests.Session | None = None,
    reintentos: int = 2,
    por_pagina: int = POR_PAGINA,
) -> tuple[pd.DataFrame, list[FuenteMeta]]:
    """Descarga un indicador anual del Banco Mundial. Devuelve `(DataFrame, fuentes)`."""
    paises = dict(paises or PAISES_POR_DEFECTO)
    hasta = hasta or date.today().year
    s = sesion or requests.Session()
    url = f"{BASE}/country/{';'.join(paises)}/indicator/{indicador}"
    registros: list[dict] = []
    pagina, total = 1, 1
    while pagina <= total:
        r = pedir(
            s, url,
            {"format": "json", "date": f"{desde}:{hasta}", "per_page": str(por_pagina), "page": str(pagina)},
            error_cls=WorldBankError, etiqueta=indicador, mensaje=_mensaje, reintentos=reintentos,
        )
        try:
            js = r.json()
        except ValueError as e:
            raise WorldBankError(f"{indicador}: la respuesta no es JSON") from e
        meta, filas = parsear_pagina(js, indicador)
        registros += filas
        total = int(meta.get("pages", 1))
        pagina += 1
    df = registros_a_df(registros, paises)
    hoy = fecha_consulta or date.today().isoformat()
    url_fuente = URL_INDICADOR.format(indicador=indicador)
    fuentes = [FuenteMeta(sr, ORGANISMO, indicador, url_fuente, hoy) for sr in df["serie"].unique()]
    return df, fuentes
