"""Fetcher del Ministerio de Inclusión, Seguridad Social y Migraciones (estadísticas de la Seguridad Social).

Portal de estadísticas: https://www.seg-social.es/wps/portal/wss/internet/EstadisticasPresupuestosEstudios/Estadisticas
No hay API: cada estadística es una página del portal con enlaces a ficheros Excel (`/wps/wcm/connect/wss/...`)
cuyo identificador cambia con cada publicación. Por eso el fetcher lee la página, busca el enlace por su nombre de
fichero y descarga el Excel. Mecanismo verificado el 2026-10-16.

Series disponibles:

- `get_afiliacion(desde=...)`: afiliados medios en alta laboral, total del sistema, media anual de las medias
  mensuales (fichero «19_Serie afiliación media por regímenes (Total Sistema)», desde enero de 2001). Solo años
  completos.
- `get_afiliacion_extranjeros(anios)`: afiliados medios extranjeros y total (ficheros anuales «Afiliación Medios
  Extranjeros AAAA», desde 2022; hoja de datos por periodo, edad, sexo y país), media anual de las medias mensuales;
  los extranjeros son todos los países salvo España (código 724). Solo años completos.
- `get_imv_titulares(anios)`: titulares del ingreso mínimo vital (hogares) por nacionalidad en la nómina de
  diciembre de cada año (dosier por comunidad autónoma y provincia, desde 2024).

Ejemplo real::

    from lib import inclusion

    df, fuentes = inclusion.get_afiliacion(desde=2001)
    # serie "afiliados": afiliados medios en alta laboral, total del sistema, media anual

Las páginas del portal pueden cambiar de dirección; las constantes `PAGINA_*` se actualizan aquí.
"""

from __future__ import annotations

import io
import re
import time
from datetime import date
from typing import Iterable

import openpyxl
import pandas as pd
import requests

from ._http import pedir
from .tipos import FuenteMeta, validar_df

ORGANISMO = "Ministerio de Inclusión, Seguridad Social y Migraciones"
BASE = "https://www.seg-social.es"
_EST = f"{BASE}/wps/portal/wss/internet/EstadisticasPresupuestosEstudios/Estadisticas"
PAGINA_AFILIACION = f"{_EST}/EST8/EST10/EST290/EST291"
PAGINA_AFILIACION_EXTRANJEROS = f"{_EST}/EST8/EST10/EST290/EST292"
PAGINA_IMV_DOSIER = f"{_EST}/cbe2fda1-3ac7-4bc8-a5ec-06c178839e11/0e716715-d290-4745-a74a-28cc1c3bc9ea"
CABECERA = {"User-Agent": "Mozilla/5.0 (compatible; EspanaenDatos)"}
MESES = "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split()
CODIGO_ESPANA = 724


class InclusionError(RuntimeError):
    """Error del portal de estadísticas de la Seguridad Social o fichero con un formato no reconocido."""


def _get(sesion: requests.Session, url: str, etiqueta: str) -> requests.Response:
    return pedir(sesion, url, None, error_cls=InclusionError, etiqueta=etiqueta, mensaje=lambda r: r.text[:200],
                 headers=CABECERA)


def enlaces(html: str) -> list[tuple[str, str]]:
    """Pares (url absoluta, texto) de los enlaces de una página del portal, sin parámetros de caché."""
    out = []
    for m in re.finditer(r'href="([^"]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
        href = m.group(1).replace("&amp;", "&")
        href = href.split("?MOD=")[0]
        if href.startswith("/"):
            href = BASE + href
        texto = re.sub(r"<[^>]+>|\s+", " ", m.group(2)).strip()
        out.append((href, texto))
    return out


def diagnostico(r: requests.Response) -> str:
    """Qué página ha llegado (estado, dirección final, título y número de enlaces), para los errores de `buscar`."""
    titulo = re.search(r"<title[^>]*>(.*?)</title>", r.text, re.S | re.I)
    titulo = re.sub(r"\s+", " ", titulo.group(1)).strip()[:80] if titulo else "sin título"
    return f"HTTP {r.status_code}, {r.url}, «{titulo}», {len(enlaces(r.text))} enlaces, {len(r.text)} caracteres"


ESPERAS_PAGINA = (5, 20, 60)  # segundos entre reintentos cuando el portal devuelve su página genérica («Content Root»)


def _pagina(sesion: requests.Session, url: str, etiqueta: str, patron: str) -> tuple[requests.Response, list[str]]:
    """Página del portal y los ficheros que cumplen `patron`. Si llega la página genérica del portal, sin
    ficheros (pasa desde GitHub Actions), lo reintenta con una sesión nueva tras `ESPERAS_PAGINA`."""
    r = _get(sesion, url, etiqueta)
    urls = buscar(r.text, patron)
    for espera in ESPERAS_PAGINA:
        if urls or "Content Root" not in r.text[:5000]:
            break
        time.sleep(espera)
        r = _get(requests.Session(), url, etiqueta)
        urls = buscar(r.text, patron)
    return r, urls


def buscar(html: str, patron: str) -> list[str]:
    """Urls de los ficheros cuyo nombre (decodificado) cumple `patron` (expresión regular, sin distinguir mayúsculas)."""
    from urllib.parse import unquote

    vistos = []
    for href, _ in enlaces(html):
        nombre = unquote(href.rsplit("/", 1)[-1]).replace("+", " ")
        if re.search(patron, nombre, re.I) and href not in vistos:
            vistos.append(href)
    return vistos


def _libro(sesion: requests.Session, url: str) -> openpyxl.Workbook:
    r = _get(sesion, url + "?MOD=AJPERES", url.rsplit("/", 1)[-1])
    try:
        return openpyxl.load_workbook(io.BytesIO(r.content), read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001 - formato no reconocido
        raise InclusionError(f"{url}: no es un Excel válido") from e


def leer_serie_afiliacion(libro: openpyxl.Workbook) -> pd.Series:
    """Afiliados medios del total del sistema por mes (índice `AAAA-MM`) en la hoja de la serie por regímenes."""
    filas = list(libro[libro.sheetnames[0]].iter_rows(values_only=True))
    cab = next((f for f in filas if f and any(str(x or "").strip().upper() == "TOTAL SISTEMA" for x in f)), None)
    if cab is None:
        raise InclusionError("serie de afiliación: no se encuentra la columna «TOTAL SISTEMA»")
    j = [str(x or "").strip().upper() for x in cab].index("TOTAL SISTEMA")
    datos = {}
    for f in filas:
        m = re.match(r"^\s*([A-Za-zÁÉÍÓÚáéíóú]+)\s+(\d{4})\s*$", str(f[0] or ""))
        if m and m.group(1).lower() in MESES and isinstance(f[j], (int, float)):
            datos[(int(m.group(2)), MESES.index(m.group(1).lower()) + 1)] = float(f[j])
    if not datos:
        raise InclusionError("serie de afiliación: sin datos mensuales")
    return pd.Series(datos).sort_index()


HOJAS_EDAD = ("Tabla_4", "DatosEdad")  # hoja de datos por periodo, edad, sexo y país (2025-: Tabla_4; 2022-2024: DatosEdad)


def leer_afiliacion_extranjeros(libro: openpyxl.Workbook) -> pd.DataFrame:
    """Afiliados medios por mes (`anio`, `mes`, `total`, `extranjeros`) de la hoja de datos por edad, sexo y país."""
    hoja = next((h for h in HOJAS_EDAD if h in libro.sheetnames), None)
    if hoja is None:
        raise InclusionError(f"afiliados extranjeros: falta la hoja de datos ({' o '.join(HOJAS_EDAD)})")
    filas = libro[hoja].iter_rows(values_only=True)
    cab = [str(x or "").strip().upper() for x in next(filas)]
    try:
        i_per, i_pais, i_val = cab.index("PERIODO"), cab.index("CODIGO_ACT"), cab.index("SALDOS")
    except ValueError as e:
        raise InclusionError(f"afiliados extranjeros: columnas inesperadas {cab}") from e
    tot: dict[int, float] = {}
    ext: dict[int, float] = {}
    for f in filas:
        if f[i_per] is None or not isinstance(f[i_val], (int, float)):
            continue
        per = int(f[i_per])
        tot[per] = tot.get(per, 0.0) + float(f[i_val])
        if f[i_pais] != CODIGO_ESPANA:
            ext[per] = ext.get(per, 0.0) + float(f[i_val])
    return pd.DataFrame(
        [(p // 100, p % 100, tot[p], ext.get(p, 0.0)) for p in sorted(tot)], columns=["anio", "mes", "total", "extranjeros"]
    )


def leer_imv_nacionalidad(libro: openpyxl.Workbook) -> tuple[float, float]:
    """(titulares, titulares de nacionalidad extranjera) de la fila «Total» de la hoja 1.5 del dosier del IMV."""
    hoja = next((h for h in libro.sheetnames if "1.5" in h), None)
    if hoja is None:
        raise InclusionError("dosier del IMV: falta la hoja 1.5 (sexo y nacionalidad de los titulares)")
    filas = list(libro[hoja].iter_rows(values_only=True))
    cab = next((f for f in filas if f and "Extranjera" in [str(x or "").strip() for x in f]), None)
    if cab is None:
        raise InclusionError("dosier del IMV: falta la columna «Extranjera»")
    j_ext = [str(x or "").strip() for x in cab].index("Extranjera")
    for f in filas:
        if f and str(f[0] or "").strip() == "Total" and isinstance(f[2], (int, float)):
            return float(f[2]), float(f[j_ext])
    raise InclusionError("dosier del IMV: falta la fila del total nacional")


def _anual(mensual: pd.Series, etiqueta: str) -> pd.Series:
    """Media anual de una serie mensual con índice (año, mes); solo años con los 12 meses."""
    df = mensual.rename("valor").reset_index()
    df.columns = ["anio", "mes", "valor"]
    cuenta = df.groupby("anio")["mes"].nunique()
    completos = cuenta[cuenta == 12].index
    if len(completos) == 0:
        raise InclusionError(f"{etiqueta}: ningún año completo")
    return df[df["anio"].isin(completos)].groupby("anio")["valor"].mean()


def get_afiliacion(*, desde: int = 1976, fecha_consulta: str | None = None,
                   sesion: requests.Session | None = None) -> tuple[pd.DataFrame, list[FuenteMeta]]:
    """Afiliados medios en alta laboral (total del sistema), media anual. Serie `afiliados`."""
    s = sesion or requests.Session()
    pagina, urls = _pagina(s, PAGINA_AFILIACION, "afiliación", r"Serie afiliaci[oó]n media por reg[ií]menes")
    if len(urls) != 1:
        raise InclusionError(
            f"afiliación: se esperaba un fichero de la serie por regímenes y hay {len(urls)} ({diagnostico(pagina)})"
        )
    anual = _anual(leer_serie_afiliacion(_libro(s, urls[0])), "afiliación")
    df = validar_df(pd.DataFrame({"serie": "afiliados", "periodo": anual.index, "valor": anual.values}))
    df = df[df["periodo"] >= desde].reset_index(drop=True)
    hoy = fecha_consulta or date.today().isoformat()
    return df, [FuenteMeta("afiliados", ORGANISMO, "Serie de afiliación media por regímenes (total del sistema)", PAGINA_AFILIACION, hoy)]


def get_afiliacion_extranjeros(anios: Iterable[int] | None = None, *, fecha_consulta: str | None = None,
                               sesion: requests.Session | None = None) -> tuple[pd.DataFrame, list[FuenteMeta]]:
    """Afiliados medios extranjeros (`afiliados_extranjeros`) y total (`afiliados_total`), media anual.

    `anios`: años de los ficheros anuales que se leen (por defecto, todos los publicados).
    """
    s = sesion or requests.Session()
    html = _get(s, PAGINA_AFILIACION_EXTRANJEROS, "afiliación de extranjeros").text
    por_anio = {}
    for url in buscar(html, r"Medios\s*Extranjeros\s*\d{4}"):
        m = re.search(r"(\d{4})", url.rsplit("/", 1)[-1])
        por_anio.setdefault(int(m.group(1)), url)
    elegidos = sorted(por_anio) if anios is None else [a for a in sorted(anios) if a in por_anio]
    filas = []
    for a in elegidos:
        mes = leer_afiliacion_extranjeros(_libro(s, por_anio[a]))
        mes = mes[mes["anio"] == a]
        if mes["mes"].nunique() != 12:
            continue  # año incompleto
        filas += [("afiliados_total", a, mes["total"].mean()), ("afiliados_extranjeros", a, mes["extranjeros"].mean())]
    if not filas:
        raise InclusionError("afiliación de extranjeros: ningún año completo")
    df = validar_df(pd.DataFrame(filas, columns=["serie", "periodo", "valor"]))
    hoy = fecha_consulta or date.today().isoformat()
    fuentes = [FuenteMeta(sr, ORGANISMO, "Afiliación medios extranjeros (ficheros anuales, datos por país)",
                          PAGINA_AFILIACION_EXTRANJEROS, hoy) for sr in df["serie"].unique()]
    return df, fuentes


def get_imv_titulares(anios: Iterable[int], *, fecha_consulta: str | None = None,
                      sesion: requests.Session | None = None) -> tuple[pd.DataFrame, list[FuenteMeta]]:
    """Titulares del IMV (`imv_titulares`) y de nacionalidad extranjera (`imv_titulares_extranjeros`) en la nómina
    de diciembre de cada año. Los años sin página o sin dosier de diciembre se omiten."""
    s = sesion or requests.Session()
    paginas = {}
    for href, texto in enlaces(_get(s, PAGINA_IMV_DOSIER, "IMV").text):
        m = re.fullmatch(r"Año (\d{4})", texto)
        if m and href.startswith(PAGINA_IMV_DOSIER):
            paginas[int(m.group(1))] = href
    filas = []
    for a in sorted(anios):
        if a not in paginas:
            continue
        urls = buscar(_get(s, paginas[a], f"IMV {a}").text, rf"^{a}12\s.*Dossier.*\.xlsx$")
        if not urls:
            continue
        total, extranjeros = leer_imv_nacionalidad(_libro(s, urls[0]))
        filas += [("imv_titulares", a, total), ("imv_titulares_extranjeros", a, extranjeros)]
    if not filas:
        raise InclusionError("IMV: ningún dosier de diciembre en los años pedidos")
    df = validar_df(pd.DataFrame(filas, columns=["serie", "periodo", "valor"]))
    hoy = fecha_consulta or date.today().isoformat()
    fuentes = [FuenteMeta(sr, ORGANISMO, "Ingreso mínimo vital, dosier de diciembre (hoja 1.5, nacionalidad de los titulares)",
                          PAGINA_IMV_DOSIER, hoy) for sr in df["serie"].unique()]
    return df, fuentes
