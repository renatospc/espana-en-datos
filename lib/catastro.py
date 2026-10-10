"""Fetcher de la Dirección General del Catastro (estadísticas de titularidad en CSV).

Documentación: https://www.catastro.hacienda.gob.es/es-ES/estadisticas_3_1.html
(metodología: https://www.catastro.hacienda.gob.es/documentos/estadisticas/metodologia_propiedad.pdf).

Mecanismo verificado el 2026-10-10: un CSV por año, nivel y tabla en
`https://www.catastro.hacienda.gob.es/documentos/estadisticas/propietarios/<año>/P_SPI_<nivel>_<tabla>.csv`
(`nivel` = `total` o `aut`; Latin-1, separador `;`). Estos padrones con tramos por número de inmuebles
existen desde 2024 y se publican a primeros de noviembre (situación a primeros de octubre). Un año no
publicado devuelve una página HTML con código 200: se detecta y lanza `CatastroError`, o se omite con
`omitir_ausentes=True`. Si el servicio cambia, actualiza este módulo y deja constancia en el Registro del ROADMAP.

Ejemplo real (viviendas cuyo titular es una persona física o jurídica privada con más de 10, y total)::

    from lib import catastro

    tramos = [f"I_U_{t}_{g}" for t in ("PF", "PJ") for g in ("HASTA_25", "HASTA_100", "MAYOR_100")]
    grandes, fuentes = catastro.get(tramos, anios=range(2024, 2027), omitir_ausentes=True)
    total, _ = catastro.get("INMUEBLES", anios=range(2024, 2027), omitir_ausentes=True)

Columnas de la tabla `V` (urbano de uso residencial): `NUM_SUJETOS_PASIVOS`, `INMUEBLES`,
`U_<tipo>_<tramo>` (titulares) e `I_U_<tipo>_<tramo>` (inmuebles), con `tipo` = `PF` (persona física),
`PJ` (persona jurídica privada), `PE` (persona jurídica pública) o `PD` (otros) y `tramo` = `HASTA_1`,
`HASTA_5`, `HASTA_10`, `HASTA_25`, `HASTA_100` o `MAYOR_100` (inmuebles del titular). El titular es el
contribuyente del IBI. Si se piden varias columnas, `valor` es su suma. Las series son `espana` (fichero
`total`) y los códigos ISO 3166-2:ES de las comunidades (fichero `aut`). El total es el territorio de
régimen común: Navarra y País Vasco tienen catastro propio y no aparecen.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from typing import Iterable, Sequence

import pandas as pd
import requests

from ._http import pedir
from .tipos import FuenteMeta, validar_df

BASE = "https://www.catastro.hacienda.gob.es/documentos/estadisticas/propietarios"
ORGANISMO = "Dirección General del Catastro"

# Columna del año: `AREF` en general, `EJERCICIO` en el total de 2024.
COLUMNAS_ANIO = ("AREF", "EJERCICIO")

# Nombre en el CSV (`CCAANOM`) → código ISO 3166-2:ES (los de CODIGOS_CCAA de src/lib/schema.ts).
CCAA = {
    "Andalucía": "ES-AN",
    "Aragón": "ES-AR",
    "Asturias (Principado de)": "ES-AS",
    "Balears (Illes)": "ES-IB",
    "Canarias": "ES-CN",
    "Cantabria": "ES-CB",
    "Castilla - La Mancha": "ES-CM",
    "Castilla y León": "ES-CL",
    "Cataluña": "ES-CT",
    "Ceuta": "ES-CE",
    "Comunidad Valenciana": "ES-VC",
    "Extremadura": "ES-EX",
    "Galicia": "ES-GA",
    "Madrid (Comunidad de)": "ES-MD",
    "Melilla": "ES-ML",
    "Murcia (Región de)": "ES-MC",
    "Rioja (La)": "ES-RI",
}


class CatastroError(RuntimeError):
    """Error del servicio del Catastro, año no publicado o fichero con un formato inesperado."""


def url_fichero(anio: int, nivel: str, tabla: str) -> str:
    return f"{BASE}/{anio}/P_SPI_{nivel}_{tabla}.csv"


def parsear_csv(contenido: bytes, url: str = "") -> list[dict[str, str]]:
    """Filas del CSV como diccionarios (cabecera → texto)."""
    texto = contenido.decode("latin-1")
    if texto.lstrip().lower().startswith(("<!doctype", "<html")):
        raise CatastroError(f"{url}: la respuesta es una página HTML, no un CSV (¿año no publicado?)")
    return list(csv.DictReader(io.StringIO(texto), delimiter=";"))


def _serie(fila: dict[str, str], nivel: str, url: str) -> str:
    if nivel == "total":
        return "espana"
    nombre = (fila.get("CCAANOM") or "").strip()
    if nombre not in CCAA:
        raise CatastroError(f"{url}: comunidad desconocida {nombre!r}; añádela a CCAA")
    return CCAA[nombre]


def get(
    columnas: str | Sequence[str],
    *,
    anios: Iterable[int],
    tabla: str = "V",
    total: bool = True,
    ccaa: bool = True,
    omitir_ausentes: bool = False,
    fecha_consulta: str | None = None,
    sesion: requests.Session | None = None,
    reintentos: int = 2,
) -> tuple[pd.DataFrame, list[FuenteMeta]]:
    """Descarga columnas de los padrones de titularidad. Devuelve `(DataFrame serie/periodo/valor, fuentes)`.

    - `columnas`: una columna o varias (se suman), p. ej. `INMUEBLES` o `I_U_PJ_MAYOR_100`.
    - `anios`: años del padrón; con `omitir_ausentes=True` se saltan los no publicados.
    - `tabla`: sufijo del fichero (`V` = urbano de uso residencial, `U` = urbano, `R` = rústico,
      `B` = bienes de características especiales).
    - `total` / `ccaa`: incluir la serie `espana` y una serie por comunidad.
    """
    cols = [columnas] if isinstance(columnas, str) else list(columnas)
    niveles = [n for n, incluir in (("total", total), ("aut", ccaa)) if incluir]
    if not cols or not niveles:
        raise ValueError("indica al menos una columna y un nivel (`total` o `ccaa`)")
    s = sesion or requests.Session()
    obs: list[tuple[str, int, float]] = []
    url_de: dict[str, str] = {}
    for anio in sorted(set(anios)):
        for nivel in niveles:
            url = url_fichero(anio, nivel, tabla)
            r = pedir(
                s, url, None, error_cls=CatastroError, etiqueta=f"P_SPI_{nivel}_{tabla} {anio}",
                mensaje=lambda r: r.text[:200], reintentos=reintentos,
            )
            try:
                filas = parsear_csv(r.content, url)
            except CatastroError:
                if omitir_ausentes:
                    break  # el año no está publicado: tampoco lo estará el otro nivel
                raise
            if not filas:
                raise CatastroError(f"{url}: CSV sin filas")
            faltan = [c for c in cols if c not in filas[0]]
            if faltan:
                raise ValueError(f"columnas inexistentes en {url}: {', '.join(faltan)}; disponibles: {', '.join(filas[0])}")
            col_anio = next((c for c in COLUMNAS_ANIO if c in filas[0]), None)
            if col_anio is None:
                raise CatastroError(f"{url}: no hay columna de año ({' ni '.join(COLUMNAS_ANIO)})")
            for f in filas:
                if (f[col_anio] or "").strip() != str(anio):
                    raise CatastroError(f"{url}: {col_anio}={f[col_anio]!r} no coincide con el año {anio}")
                serie = _serie(f, nivel, url)
                obs.append((serie, anio, float(sum(int(f[c]) for c in cols))))
                url_de[serie] = url
    if not obs:
        raise CatastroError("ningún año pedido está publicado")
    df = validar_df(pd.DataFrame(obs, columns=["serie", "periodo", "valor"]))
    codigo = f"Titularidad catastral, P_SPI_<nivel>_{tabla} ({' + '.join(cols)})"
    hoy = fecha_consulta or date.today().isoformat()
    fuentes = [FuenteMeta(sr, ORGANISMO, codigo, url_de[sr], hoy) for sr in df["serie"].unique()]
    return df, fuentes
