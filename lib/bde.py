"""Fetcher del Banco de España (servicio REST del Boletín Estadístico, BIEST).

Mecanismo verificado el 2026-10-08: `https://app.bde.es/bierest/resources/srdatosapp/listaSeries`
(JSON; parámetros `idioma`, `series`, `rango`). Los códigos de serie se obtienen en el
Boletín Estadístico (https://www.bde.es/webbe/es/estadisticas/). Si el servicio cambia,
actualiza este módulo y deja constancia en el Registro del ROADMAP.

Ejemplo real (Euribor a un año, mensual → media anual)::

    from lib import bde

    df, fuentes = bde.get({"D_1NBAF472": "espana"}, agregacion="media")

`series` mapea el código de serie del BdE al id de serie de la gráfica. Si la serie no es
anual hay que indicar `agregacion` (`media`, `suma` o `ultimo`); solo se agregan años
completos. El servicio devuelve la serie entera (`rango=MAX`) sin paginación; el filtro por
`desde` se aplica en el cliente.
"""

from __future__ import annotations

from datetime import date
from typing import Mapping

import pandas as pd
import requests

from ._http import pedir
from ._anual import agregar_anual
from .tipos import FuenteMeta

BASE = "https://app.bde.es/bierest/resources/srdatosapp/listaSeries"
ORGANISMO = "Banco de España"


class BdeError(RuntimeError):
    """Error del servicio del Banco de España o fallo de red persistente."""


def _mensaje(r: requests.Response) -> str:
    try:
        js = r.json()
        return f"{js.get('errMsgUsr', '')}: {js.get('errMsgDebug', '')}"
    except ValueError:
        return r.text[:200]


def parsear_series(js: object) -> dict[str, tuple[pd.DataFrame, str]]:
    """`{código: (observaciones anio/orden/valor, frecuencia)}` de la respuesta de `listaSeries`."""
    if isinstance(js, dict) and "errNum" in js:
        raise BdeError(f"error de la API: {js.get('errMsgUsr')}: {js.get('errMsgDebug')}")
    if not isinstance(js, list):
        raise BdeError("respuesta no reconocida")
    out = {}
    for s in js:
        fechas, valores = s["fechas"], s["valores"]
        if len(fechas) != len(valores):
            raise BdeError(f"{s['serie']}: fechas y valores de distinta longitud")
        df = pd.DataFrame(
            {"anio": [int(f[:4]) for f in fechas], "orden": fechas, "valor": valores}
        )
        df["valor"] = pd.to_numeric(df["valor"])
        out[s["serie"]] = (df, s.get("codFrecuencia", ""))
    return out


def get(
    series: Mapping[str, str],
    *,
    agregacion: str | None = None,
    desde: int = 1976,
    fecha_consulta: str | None = None,
    sesion: requests.Session | None = None,
    reintentos: int = 2,
    rango: str = "MAX",
) -> tuple[pd.DataFrame, list[FuenteMeta]]:
    """Descarga series del BdE como anuales. Devuelve `(DataFrame serie/periodo/valor, fuentes)`."""
    r = pedir(
        sesion or requests.Session(), BASE,
        {"idioma": "es", "series": ",".join(series), "rango": rango},
        error_cls=BdeError, etiqueta=",".join(series), mensaje=_mensaje, reintentos=reintentos,
    )
    try:
        recibidas = parsear_series(r.json())
    except ValueError as e:
        raise BdeError("la respuesta no es JSON") from e
    faltan = set(series) - set(recibidas)
    if faltan:
        raise BdeError(f"series no devueltas: {', '.join(sorted(faltan))}")
    partes = []
    for codigo, (obs, _freq) in recibidas.items():
        obs = obs[obs["anio"] >= desde].copy()
        obs.insert(0, "serie", series[codigo])
        partes.append(obs)
    df = agregar_anual(pd.concat(partes, ignore_index=True), agregacion, "BdE ")
    hoy = fecha_consulta or date.today().isoformat()
    cod_de = {v: k for k, v in series.items()}
    fuentes = [
        FuenteMeta(
            sr, ORGANISMO, cod_de[sr],
            f"{BASE}?idioma=es&series={cod_de[sr]}&rango=MAX", hoy,
        )
        for sr in df["serie"].unique()
    ]
    return df, fuentes
