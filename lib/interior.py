"""Fetcher del Ministerio del Interior: Sistema Estadístico de Criminalidad (SEC), allanamiento y usurpación de inmuebles.

Portal: https://estadisticasdecriminalidad.ses.mir.es/publico/portalestadistico/
La tabla «Allanamiento / Usurpación de inmuebles» (carpeta `Datos11`, series anuales desde 2010) se publica en el
servicio PC-Axis del portal, que ofrece cada tabla en CSV. Mecanismo verificado el 2026-10-19: sin cabecera
`User-Agent` de navegador el servidor responde 403.

La serie **mezcla** dos delitos del Código Penal: el allanamiento de morada (arts. 202 y 203) y la usurpación de
inmuebles (art. 245, con o sin violencia y sean o no viviendas). Interior no publica un desglose por delito ni por
tipo de inmueble en estas tablas.

- `get(tabla, territorios)`: una de las cuatro tablas por comunidad autónoma (`hechos_conocidos`,
  `hechos_esclarecidos`, `detenciones_investigados`, `victimizaciones`); `territorios` mapea el nombre de la fila
  (como lo escribe el portal: «TOTAL NACIONAL», «CATALUÑA»…) al id de serie de la gráfica.

Ejemplo real::

    from lib import interior

    df, fuentes = interior.get("hechos_conocidos", {"TOTAL NACIONAL": "espana"}, desde=2010)

La respuesta va en UTF-8 con BOM (la cabecera HTTP dice ISO-8859-15), separa con `;` y usa `.` como separador de miles.
"""

from __future__ import annotations

import io
from datetime import date
from typing import Mapping

import pandas as pd
import requests

from ._http import pedir
from .tipos import FuenteMeta, validar_df

ORGANISMO = "Ministerio del Interior"
BASE = "https://estadisticasdecriminalidad.ses.mir.es/sec/jaxiPx"
URL_CSV = BASE + "/files/_px/es/csv_bdsc/Datos11/l0/{tabla}.csv_bdsc?nocab=1"
URL_TABLA = BASE + "/Tabla.htm?path=/Datos11/l0/&file={tabla}.px&L=0"
CABECERA = {"User-Agent": "Mozilla/5.0 (compatible; EspanaenDatos)"}
# Tablas por comunidad autónoma (las de provincias son 11002, 11004, 11006 y 11008)
TABLAS = {
    "hechos_conocidos": "11001",
    "hechos_esclarecidos": "11003",
    "detenciones_investigados": "11005",
    "victimizaciones": "11007",
}


class InteriorError(RuntimeError):
    """Error del portal de Interior o tabla con un formato no reconocido."""


def parsear_csv(contenido: bytes, tabla: str) -> pd.DataFrame:
    """Filas `territorio, periodo, valor` del CSV de una tabla; las celdas vacías quedan en NaN."""
    try:
        texto = contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = contenido.decode("iso-8859-15")
    df = pd.read_csv(io.StringIO(texto), sep=";", thousands=".", dtype={"periodo": "Int64"})
    if df.shape[1] != 3 or df.columns[1] != "periodo":
        raise InteriorError(f"{tabla}: columnas inesperadas {list(df.columns)}")
    df.columns = ["territorio", "periodo", "valor"]
    df["territorio"] = df["territorio"].astype(str).str.strip()
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    return df.dropna(subset=["periodo"])


def get(
    tabla: str,
    territorios: Mapping[str, str],
    *,
    desde: int = 1976,
    fecha_consulta: str | None = None,
    sesion: requests.Session | None = None,
    reintentos: int = 2,
) -> tuple[pd.DataFrame, list[FuenteMeta]]:
    """Descarga una tabla de allanamiento / usurpación de inmuebles. Devuelve `(DataFrame serie/periodo/valor, fuentes)`."""
    if tabla not in TABLAS:
        raise ValueError(f"tabla {tabla!r} no válida; usa {', '.join(TABLAS)}")
    codigo = TABLAS[tabla]
    r = pedir(
        sesion or requests.Session(), URL_CSV.format(tabla=codigo), None,
        error_cls=InteriorError, etiqueta=codigo, mensaje=lambda r: r.text[:200], headers=CABECERA, reintentos=reintentos,
    )
    obs = parsear_csv(r.content, codigo)
    faltan = [t for t in territorios if t not in set(obs["territorio"])]
    if faltan:
        raise InteriorError(f"{codigo}: faltan los territorios {faltan}")
    obs = obs[obs["territorio"].isin(territorios) & (obs["periodo"] >= desde)]
    df = validar_df(pd.DataFrame({
        "serie": obs["territorio"].map(territorios), "periodo": obs["periodo"].astype("int64"), "valor": obs["valor"],
    }).dropna(subset=["valor"]))
    hoy = fecha_consulta or date.today().isoformat()
    fuentes = [
        FuenteMeta(s, ORGANISMO, f"Sistema Estadístico de Criminalidad, tabla {codigo}", URL_TABLA.format(tabla=codigo), hoy)
        for s in df["serie"].unique()
    ]
    return df, fuentes
