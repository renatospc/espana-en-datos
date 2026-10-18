"""Fetcher de Eurostat (API de difusión, formato JSON-stat 2.0).

Documentación de la API: https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access/api-getting-started

Ejemplo real (desempleo anual, % de población activa, 15-74 años)::

    from lib import eurostat

    df, fuentes = eurostat.get(
        "une_rt_a",
        {"age": "Y15-74", "sex": "T", "unit": "PC_ACT"},
        geos={"ES": "espana", "EU27_2020": "ue27"},
        desde=1976,
    )

`filtros` debe fijar todas las dimensiones del dataset salvo `geo` y `time`
(un solo valor por dimensión); si queda alguna con varios valores se lanza
`ValueError`. Solo se admiten periodos anuales. La API de difusión no pagina:
una consulta que supera el límite de celdas devuelve un error, que se propaga
como `EurostatError` (acota los filtros o `desde`).

Los geos que Eurostat no publica (p. ej. `US`, `CA`) no aparecen en el DataFrame
ni en `fuentes`: el notebook los completa con `null` (METODOLOGIA §2.4) u otra fuente.

`get_estados` descarga las marcas de estado de las mismas celdas (p. ej. `b` = ruptura de serie,
`u` = fiabilidad baja, `p` = provisional), para documentarlas en las notas (METODOLOGIA §2.5).
"""

from __future__ import annotations

import math
import re
import time
from datetime import date
from typing import Mapping

import pandas as pd
import requests

from .tipos import COLUMNAS, FuenteMeta, validar_df

BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
URL_DATABROWSER = "https://ec.europa.eu/eurostat/databrowser/view/{dataset}/default/table?lang=en"
ORGANISMO = "Eurostat"
GEOS_POR_DEFECTO = {"ES": "espana", "EU27_2020": "ue27"}

_ANIO = re.compile(r"^\d{4}$")


class EurostatError(RuntimeError):
    """Error devuelto por la API de Eurostat o fallo de red persistente."""


def _pedir(dataset: str, params: list[tuple[str, str]], sesion: requests.Session, reintentos: int) -> dict:
    url = f"{BASE}/{dataset}"
    ultimo: Exception | None = None
    for intento in range(reintentos + 1):
        try:
            r = sesion.get(url, params=params, timeout=60)
        except requests.RequestException as e:
            ultimo = e
        else:
            if r.status_code < 400:
                return parsear_respuesta(r.json())
            if r.status_code < 500 and r.status_code != 429:
                raise EurostatError(_mensaje_error(r, dataset))
            ultimo = EurostatError(_mensaje_error(r, dataset))
        if intento < reintentos:
            time.sleep(2**intento)
    raise EurostatError(f"{dataset}: la consulta falló tras {reintentos + 1} intentos: {ultimo}")


def _mensaje_error(r: requests.Response, dataset: str) -> str:
    try:
        detalle = "; ".join(e.get("label", "") for e in r.json().get("error", []))
    except ValueError:
        detalle = r.text[:200]
    return f"{dataset}: HTTP {r.status_code}: {detalle}"


def parsear_respuesta(js: dict) -> dict:
    """Comprueba que la respuesta es un dataset JSON-stat y la devuelve."""
    if "error" in js:
        detalle = "; ".join(e.get("label", "") for e in js["error"])
        raise EurostatError(f"error de la API: {detalle}")
    if js.get("class") != "dataset" or "dimension" not in js:
        raise EurostatError("respuesta no reconocida (no es un dataset JSON-stat)")
    return js


def jsonstat_a_df(js: dict, geos: Mapping[str, str], dataset: str = "") -> pd.DataFrame:
    """Convierte un dataset JSON-stat al DataFrame estándar `serie, periodo, valor`.

    Solo se admite `geo` y `time` con más de una categoría. Los geos fuera de `geos` se ignoran.
    """
    ids, tamanos = js["id"], js["size"]
    cats = {
        d: list(js["dimension"][d]["category"]["index"].keys())
        if isinstance(js["dimension"][d]["category"]["index"], dict)
        else list(js["dimension"][d]["category"]["index"])
        for d in ids
    }
    multiples = [d for d, n in zip(ids, tamanos) if n > 1 and d not in ("geo", "time")]
    if multiples:
        raise ValueError(
            f"{dataset}: dimensiones con varios valores, fíjalas en `filtros`: "
            + ", ".join(f"{d} ({', '.join(cats[d][:5])}…)" for d in multiples)
        )
    if "geo" not in ids or "time" not in ids:
        raise EurostatError(f"{dataset}: faltan las dimensiones geo/time")
    for t in cats["time"]:
        if not _ANIO.match(t):
            raise ValueError(f"{dataset}: periodo no anual {t!r}; solo se admiten años")

    # Pasos (strides) del índice plano en orden de `id`.
    pasos, acc = {}, 1
    for d, n in reversed(list(zip(ids, tamanos))):
        pasos[d] = acc
        acc *= n

    valores = js.get("value", {})
    if isinstance(valores, list):
        valores = {str(i): v for i, v in enumerate(valores) if v is not None}

    filas = []
    for g, geo in enumerate(cats["geo"]):
        if geo not in geos:
            continue
        for t, anio in enumerate(cats["time"]):
            v = valores.get(str(g * pasos["geo"] + t * pasos["time"]))
            filas.append((geos[geo], int(anio), math.nan if v is None else float(v)))
    df = pd.DataFrame(filas, columns=COLUMNAS)
    # Una serie sin ningún dato no existe: se omite (el notebook la rellena con null).
    con_dato = df.groupby("serie")["valor"].transform(lambda s: s.notna().any())
    df = df[con_dato].dropna(subset=["valor"])
    return validar_df(df)


def _descargar(
    dataset: str,
    filtros: Mapping[str, str],
    geos: Mapping[str, str],
    desde: int,
    sesion: requests.Session | None,
    reintentos: int,
) -> dict:
    for dim, val in filtros.items():
        if not isinstance(val, str):
            raise ValueError(f"filtro {dim!r}: se espera un único código (str), no {val!r}")
    params = [("format", "JSON"), ("lang", "EN"), ("sinceTimePeriod", str(desde))]
    params += [(dim, val) for dim, val in filtros.items()]
    params += [("geo", g) for g in geos]
    return _pedir(dataset, params, sesion or requests.Session(), reintentos)


def jsonstat_estados(js: dict, geos: Mapping[str, str]) -> tuple[pd.DataFrame, dict[str, str]]:
    """Marcas de estado de un dataset JSON-stat: `(DataFrame serie/periodo/estado, {código: etiqueta})`.

    Solo las celdas con marca; mismas restricciones que `jsonstat_a_df` (una celda por geo y año).
    """
    ids, tamanos = js["id"], js["size"]
    cats = {
        d: list(js["dimension"][d]["category"]["index"].keys())
        if isinstance(js["dimension"][d]["category"]["index"], dict)
        else list(js["dimension"][d]["category"]["index"])
        for d in ids
    }
    if any(n > 1 and d not in ("geo", "time") for d, n in zip(ids, tamanos)):
        raise ValueError("dimensiones con varios valores, fíjalas en `filtros`")
    pasos, acc = {}, 1
    for d, n in reversed(list(zip(ids, tamanos))):
        pasos[d] = acc
        acc *= n
    estados = js.get("status", {})
    if isinstance(estados, list):
        estados = {str(i): v for i, v in enumerate(estados) if v}
    filas = []
    for g, geo in enumerate(cats["geo"]):
        if geo not in geos:
            continue
        for t, anio in enumerate(cats["time"]):
            e = estados.get(str(g * pasos["geo"] + t * pasos["time"]))
            if e:
                filas.append((geos[geo], int(anio), e))
    etiquetas = js.get("extension", {}).get("status", {}).get("label", {})
    df = pd.DataFrame(filas, columns=["serie", "periodo", "estado"])
    return df.sort_values(["serie", "periodo"]).reset_index(drop=True), dict(etiquetas)


def get_estados(
    dataset: str,
    filtros: Mapping[str, str],
    *,
    geos: Mapping[str, str] | None = None,
    desde: int = 1976,
    sesion: requests.Session | None = None,
    reintentos: int = 2,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Marcas de estado de las celdas que descargaría `get` con los mismos argumentos.

    Devuelve `(DataFrame serie/periodo/estado, {código: etiqueta})`, p. ej. `("espana", 2021, "b")`
    y `{"b": "break in time series"}`. Una marca puede combinar varios códigos (`"bu"`).
    """
    geos = dict(geos or GEOS_POR_DEFECTO)
    return jsonstat_estados(_descargar(dataset, filtros, geos, desde, sesion, reintentos), geos)


def get(
    dataset: str,
    filtros: Mapping[str, str],
    *,
    geos: Mapping[str, str] | None = None,
    desde: int = 1976,
    fecha_consulta: str | None = None,
    sesion: requests.Session | None = None,
    reintentos: int = 2,
) -> tuple[pd.DataFrame, list[FuenteMeta]]:
    """Descarga un dataset de Eurostat. Devuelve `(DataFrame serie/periodo/valor, fuentes)`.

    - `filtros`: dimensión → código (un valor cada una), p. ej. `{"unit": "PC_ACT", "sex": "T"}`.
    - `geos`: código Eurostat → id de serie (por defecto `ES→espana`, `EU27_2020→ue27`).
    - `desde`: primer año solicitado (`sinceTimePeriod`).
    Se devuelve una `FuenteMeta` por serie con datos.
    """
    geos = dict(geos or GEOS_POR_DEFECTO)
    js = _descargar(dataset, filtros, geos, desde, sesion, reintentos)
    df = jsonstat_a_df(js, geos, dataset)
    hoy = fecha_consulta or date.today().isoformat()
    url = URL_DATABROWSER.format(dataset=dataset)
    fuentes = [FuenteMeta(serie, ORGANISMO, dataset, url, hoy) for serie in df["serie"].unique()]
    return df, fuentes


# Marcas de estado de Eurostat, en español, para las notas.
ESTADOS = {
    "b": "ruptura de serie",
    "c": "dato confidencial",
    "d": "definición distinta (ver los metadatos de Eurostat)",
    "e": "dato estimado",
    "f": "previsión",
    "n": "dato no significativo",
    "p": "dato provisional",
    "r": "dato revisado",
    "s": "estimación de Eurostat",
    "u": "fiabilidad baja",
    "z": "no aplicable",
}


def _intervalos(años: list[int]) -> str:
    """[2013, 2014, 2015, 2021] → «2013-2015 y 2021»."""
    tramos: list[list[int]] = []
    for a in sorted(set(años)):
        if tramos and a == tramos[-1][-1] + 1:
            tramos[-1].append(a)
        else:
            tramos.append([a])
    textos = [str(t[0]) if len(t) == 1 else f"{t[0]}-{t[-1]}" for t in tramos]
    return textos[0] if len(textos) == 1 else f"{', '.join(textos[:-1])} y {textos[-1]}"


def nota_estados(estados: pd.DataFrame, nombres: Mapping[str, str], codigos: str = "bdu") -> list[str]:
    """Una nota por marca de `codigos` presente en `estados` (de `get_estados`), con las series y sus años.

    `nombres` da el nombre que ve el lector de cada serie, en el orden en que se citan; las series
    que no están en `nombres` se ignoran. Ejemplo: «Eurostat marca ruptura de serie en: España (2005 y
    2021) y UE-27 (2021).»
    """
    notas = []
    for codigo in codigos:
        partes = []
        for serie, nombre in nombres.items():
            filas = estados[(estados["serie"] == serie) & estados["estado"].str.contains(codigo, regex=False)]
            if not filas.empty:
                partes.append(f"{nombre} ({_intervalos(filas['periodo'].tolist())})")
        if partes:
            lista = partes[0] if len(partes) == 1 else f"{'; '.join(partes[:-1])}; y {partes[-1]}"
            notas.append(f"Eurostat marca {ESTADOS.get(codigo, codigo)} en: {lista}.")
    return notas
