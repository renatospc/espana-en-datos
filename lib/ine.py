"""Fetcher del INE (API JSON Tempus3, servicio `DATOS_SERIE`).

Documentación: https://www.ine.es/dyngs/DAB/index.htm?cid=1100

Ejemplo real (IPC general, índice, base 2021; mensual → media anual)::

    from lib import ine

    df, fuentes = ine.get({"IPC251852": "espana"}, agregacion="media")

`series` mapea el código de serie del INE (se obtiene en la ficha de la serie en INEbase,
campo «Código de serie») al id de serie de la gráfica. Si la serie no es anual hay que
indicar `agregacion` (`media`, `suma` o `ultimo`); solo se agregan años completos. La API
devuelve la serie entera en una respuesta (sin paginación). Los valores `Secreto` o nulos se omiten.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Mapping

import pandas as pd
import requests

from ._http import pedir
from ._anual import agregar_anual
from .tipos import FuenteMeta

BASE = "https://servicios.ine.es/wstempus/js/ES/DATOS_SERIE"
URL_SERIE = "https://www.ine.es/consul/serie.do?s={codigo}"
ORGANISMO = "INE"


class IneError(RuntimeError):
    """Error de la API del INE o fallo de red persistente."""


def parsear_serie(texto: str, codigo: str) -> pd.DataFrame:
    """Observaciones `anio, orden, valor` de la respuesta de `DATOS_SERIE`.

    El INE responde HTTP 200 con cuerpo vacío o `{"status": ...}` si la serie no existe.
    """
    if not texto.strip():
        raise IneError(f"{codigo}: respuesta vacía (¿existe la serie?)")
    try:
        js = json.loads(texto)
    except ValueError as e:
        raise IneError(f"{codigo}: la respuesta no es JSON") from e
    if not isinstance(js, dict) or "Data" not in js:
        raise IneError(f"{codigo}: error de la API: {str(js)[:200]}")
    filas = [
        (d["Anyo"], d["Fecha"], None if d.get("Secreto") else d.get("Valor"))
        for d in js["Data"]
    ]
    df = pd.DataFrame(filas, columns=["anio", "orden", "valor"])
    df["valor"] = pd.to_numeric(df["valor"])
    return df


def get(
    series: Mapping[str, str],
    *,
    agregacion: str | None = None,
    desde: int = 1976,
    hasta: int | None = None,
    fecha_consulta: str | None = None,
    sesion: requests.Session | None = None,
    reintentos: int = 2,
) -> tuple[pd.DataFrame, list[FuenteMeta]]:
    """Descarga series del INE como anuales. Devuelve `(DataFrame serie/periodo/valor, fuentes)`."""
    hasta = hasta or date.today().year
    s = sesion or requests.Session()
    partes = []
    for codigo, serie in series.items():
        r = pedir(
            s, f"{BASE}/{codigo}", {"date": f"{desde}0101:{hasta}1231"},
            error_cls=IneError, etiqueta=codigo, mensaje=lambda r: r.text[:200], reintentos=reintentos,
        )
        obs = parsear_serie(r.text, codigo)
        obs.insert(0, "serie", serie)
        partes.append(obs)
    obs = pd.concat(partes, ignore_index=True)
    df = agregar_anual(obs, agregacion, "INE ")
    hoy = fecha_consulta or date.today().isoformat()
    cod_de = {v: k for k, v in series.items()}
    fuentes = [
        FuenteMeta(sr, ORGANISMO, cod_de[sr], URL_SERIE.format(codigo=cod_de[sr]), hoy)
        for sr in df["serie"].unique()
    ]
    return df, fuentes
