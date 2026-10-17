"""Fetcher del Boletín de Estadísticas Laborales (BEL) del Ministerio de Trabajo y Economía Social.

Índice: https://www.mites.gob.es/estadisticas/bel/welcome.htm
Cada tabla es un fichero Excel antiguo (`.xls`) en `https://www.mites.gob.es/estadisticas/bel/<SECCION>/<tabla>.xls`
(p. ej. `PEN/pen1.xls`), con las medias anuales de los últimos años y los datos mensuales recientes. Mecanismo
verificado el 2026-10-16. Las cifras de pensiones y afiliación del BEL son las de la Seguridad Social (Ministerio de
Inclusión, Seguridad Social y Migraciones), que el Ministerio de Trabajo publica en series anuales.

- `get_pensiones()`: pensiones contributivas en vigor del sistema de la Seguridad Social, total, media anual de los
  datos del primer día de cada mes (PEN-1, columna «Número» del total, en miles → se devuelve en pensiones). Serie
  `pensiones`.

Ejemplo real::

    from lib import bel

    df, fuentes = bel.get_pensiones()
"""

from __future__ import annotations

import re
from datetime import date

import pandas as pd
import requests
import xlrd

from ._http import pedir, sesion_fnmt
from .tipos import FuenteMeta, validar_df

ORGANISMO = "Ministerio de Trabajo y Economía Social"
BASE = "https://www.mites.gob.es/estadisticas/bel"
CABECERA = {"User-Agent": "Mozilla/5.0 (compatible; EspanaenDatos)"}


class BelError(RuntimeError):
    """Error de la web del BEL o tabla con un formato no reconocido."""


def leer_anuales(contenido: bytes, etiqueta: str = "") -> dict[int, list]:
    """Filas anuales («2016...........») de la primera hoja de una tabla del BEL: {año: fila}."""
    try:
        hoja = xlrd.open_workbook(file_contents=contenido).sheet_by_index(0)
    except xlrd.XLRDError as e:
        raise BelError(f"{etiqueta}: no es un .xls válido") from e
    out = {}
    for i in range(hoja.nrows):
        fila = hoja.row_values(i)
        m = re.match(r"^\s*(\d{4})\.*\s*$", str(fila[0]))
        if m:
            out[int(m.group(1))] = fila
    if not out:
        raise BelError(f"{etiqueta}: sin filas anuales")
    return out


def get_pensiones(*, desde: int = 1976, fecha_consulta: str | None = None,
                  sesion: requests.Session | None = None) -> tuple[pd.DataFrame, list[FuenteMeta]]:
    """Pensiones contributivas en vigor (total), media anual, en número de pensiones (serie `pensiones`)."""
    url = f"{BASE}/PEN/pen1.xls"
    r = pedir(sesion or sesion_fnmt(), url, None, error_cls=BelError, etiqueta="PEN-1",
              mensaje=lambda r: r.text[:200], headers=CABECERA)
    anuales = leer_anuales(r.content, "PEN-1")
    # Columna 1: número total de pensiones (miles); columna 2: importe medio.
    filas = [("pensiones", a, float(f[1]) * 1000) for a, f in anuales.items() if isinstance(f[1], float) and a >= desde]
    df = validar_df(pd.DataFrame(filas, columns=["serie", "periodo", "valor"]))
    hoy = fecha_consulta or date.today().isoformat()
    return df, [FuenteMeta("pensiones", ORGANISMO, "BEL, PEN-1 (pensiones contributivas en vigor, total, media anual)", url, hoy)]
