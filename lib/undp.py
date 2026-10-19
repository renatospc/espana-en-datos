"""Fetcher del Informe sobre Desarrollo Humano del PNUD (fichero CSV de las series de los índices compuestos).

Documentación: https://hdr.undp.org/data-center/documentation-and-downloads
El PNUD publica con cada edición del informe un único CSV con todas las series de los índices
compuestos (IDH, IDH ajustado por la desigualdad, índices de género...), una columna por indicador y
año (`ihdi_2010`, `hdi_2023`...) y una fila por país o agregado (`iso3`; los agregados empiezan por
`ZZ`, p. ej. `ZZK.WORLD`). Verificado el 2026-10-18 con la edición de 2025 (datos hasta 2023).

Ejemplo real (IDH ajustado por la desigualdad, de 0 a 1)::

    from lib import undp

    df, fuentes = undp.get("ihdi", paises={"ESP": "espana", "USA": "eeuu", "CAN": "canada"})

Las celdas vacías son dato ausente; los países sin datos no aparecen en el resultado ni en `fuentes`.
`FICHERO` y `EDICION` se actualizan a mano con cada informe nuevo (el nombre del fichero cambia).
"""

from __future__ import annotations

import io
import re
from datetime import date
from typing import Mapping

import pandas as pd
import requests

from ._http import pedir
from .tipos import FuenteMeta, validar_df

EDICION = "2025"
FICHERO = "2025_HDR/HDR25_Composite_indices_complete_time_series.csv"
BASE = "https://hdr.undp.org/sites/default/files"
URL_DOCUMENTACION = "https://hdr.undp.org/data-center/documentation-and-downloads"
ORGANISMO = "PNUD"
PAISES_POR_DEFECTO = {"ESP": "espana", "USA": "eeuu", "CAN": "canada"}


class UndpError(RuntimeError):
    """Error al descargar o leer el fichero del Informe sobre Desarrollo Humano."""


def leer_csv(texto: str, indicador: str, paises: Mapping[str, str], desde: int = 1976) -> pd.DataFrame:
    """Columnas `<indicador>_<año>` del CSV → DataFrame `serie, periodo, valor` de los `paises` pedidos."""
    tabla = pd.read_csv(io.StringIO(texto), dtype=str, keep_default_na=False)
    if "iso3" not in tabla.columns:
        raise UndpError("el fichero no tiene la columna iso3 (¿ha cambiado el formato?)")
    patron = re.compile(rf"^{re.escape(indicador)}_(\d{{4}})$")
    columnas = {c: int(m.group(1)) for c in tabla.columns if (m := patron.match(c))}
    if not columnas:
        raise UndpError(f"el fichero no tiene columnas {indicador}_<año>")
    filas = []
    for _, fila in tabla[tabla["iso3"].isin(paises)].iterrows():
        for col, anio in columnas.items():
            v = fila[col].strip()
            if v and anio >= desde:
                filas.append({"serie": paises[fila["iso3"]], "periodo": anio, "valor": float(v)})
    return validar_df(pd.DataFrame(filas, columns=["serie", "periodo", "valor"]))


def get(
    indicador: str,
    *,
    paises: Mapping[str, str] | None = None,
    desde: int = 1976,
    fecha_consulta: str | None = None,
    sesion: requests.Session | None = None,
    reintentos: int = 2,
) -> tuple[pd.DataFrame, list[FuenteMeta]]:
    """Descarga una serie del CSV de índices compuestos. Devuelve `(DataFrame serie/periodo/valor, fuentes)`.

    `paises`: código ISO3 (o de agregado del PNUD) → id de serie (por defecto ESP, USA y CAN).
    """
    paises = dict(paises or PAISES_POR_DEFECTO)
    url = f"{BASE}/{FICHERO}"
    r = pedir(
        sesion or requests.Session(), url, None, error_cls=UndpError, etiqueta=f"PNUD {indicador}",
        mensaje=lambda r: r.text[:200], reintentos=reintentos,
    )
    texto = r.content.decode("latin-1") if isinstance(r.content, bytes) else r.text
    df = leer_csv(texto, indicador, paises, desde)
    hoy = fecha_consulta or date.today().isoformat()
    codigo = f"Human Development Report {EDICION}, índices compuestos ({indicador})"
    fuentes = [FuenteMeta(s, ORGANISMO, codigo, URL_DOCUMENTACION, hoy) for s in df["serie"].unique()]
    return df, fuentes
