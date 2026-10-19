"""Fetcher del IMSERSO (Ministerio de Derechos Sociales): pensiones no contributivas (PNC) de jubilación e incapacidad.

Página de estadísticas: https://imserso.es/el-imserso/documentacion/estadisticas/pensiones-no-contributivas-jubilacion-incapacidad-pnc
No hay API: la página enlaza ficheros PDF, Excel y CSV (`/documents/20123/121856/<nombre>.csv/<uuid>`) cuyo
identificador cambia con cada publicación. El fetcher lee la página, busca el enlace por el nombre del fichero y
descarga el CSV. Mecanismo verificado el 2026-10-19. Los CSV van en ISO-8859-1, separados por `;`, con `.` como
separador de miles y `,` decimal.

Series disponibles:

- `get_evolucion(anios)`: fichero `evolpncs.csv` («Evolución pensiones e importes de las nóminas a nivel estatal»,
  total Estado con Navarra y País Vasco, desde 2019). Una fila por año completo (las mensualidades del año en curso
  no se agregan). Series `pensiones_jubilacion`, `pensiones_incapacidad`, `pensiones_total` (número de pensiones
  en la nómina del año; el IMSERSO publica el de diciembre) e `importe_jubilacion`, `importe_incapacidad`,
  `importe_total` (importes brutos del año, en euros).

El IMSERSO **no publica la nacionalidad** de los pensionistas: el «Perfil del pensionista» (Excel, diciembre de
2025) desglosa por sexo, edad, estado civil, convivencia y discapacidad, pero no por país. Por eso el fetcher no
tiene serie por nacionalidad.

Ejemplo real::

    from lib import imserso

    df, fuentes = imserso.get_evolucion()
    # serie "pensiones_total": número de pensiones no contributivas en la nómina de cada año
"""

from __future__ import annotations

import io
import re
from datetime import date
from typing import Iterable
from urllib.parse import unquote

import pandas as pd
import requests

from ._http import pedir
from .tipos import FuenteMeta, validar_df

ORGANISMO = "Ministerio de Derechos Sociales, Consumo y Agenda 2030 (IMSERSO)"
BASE = "https://imserso.es"
PAGINA_PNC = f"{BASE}/el-imserso/documentacion/estadisticas/pensiones-no-contributivas-jubilacion-incapacidad-pnc"
FICHERO_EVOLUCION = "evolpncs.csv"
CABECERA = {"User-Agent": "Mozilla/5.0 (compatible; EspanaenDatos)"}
SERIES = ("pensiones_jubilacion", "pensiones_incapacidad", "pensiones_total",
          "importe_jubilacion", "importe_incapacidad", "importe_total")


class ImsersoError(RuntimeError):
    """Error de la web del IMSERSO o fichero con un formato no reconocido."""


def _get(sesion: requests.Session, url: str, etiqueta: str) -> requests.Response:
    return pedir(sesion, url, None, error_cls=ImsersoError, etiqueta=etiqueta, mensaje=lambda r: r.text[:200],
                 headers=CABECERA)


def buscar(html: str, nombre: str) -> list[str]:
    """Urls absolutas de los enlaces a ficheros cuyo nombre es exactamente `nombre` (p. ej. `evolpncs.csv`)."""
    vistos = []
    for href in re.findall(r'href="([^"]+)"', html):
        href = href.replace("&amp;", "&")
        partes = unquote(href).split("/")
        if len(partes) >= 2 and partes[-2] == nombre:
            url = BASE + href if href.startswith("/") else href
            if url not in vistos:
                vistos.append(url)
    return vistos


def _numero(celda: str) -> float | None:
    celda = celda.strip()
    if not celda:
        return None
    try:
        return float(celda.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def parsear_evolucion(contenido: bytes) -> pd.DataFrame:
    """Filas anuales (`anio` y las seis series) del CSV de evolución de las nóminas."""
    texto = contenido.decode("utf-8-sig") if contenido[:3] == b"\xef\xbb\xbf" else contenido.decode("iso-8859-1")
    filas = []
    for linea in io.StringIO(texto):
        celdas = linea.rstrip("\r\n").split(";")
        m = re.fullmatch(r"\s*AÑO\s+(\d{4})\s*", celdas[1]) if len(celdas) > 9 else None
        if not m:
            continue
        valores = [_numero(c) for c in (celdas[3], celdas[4], celdas[5], celdas[7], celdas[8], celdas[9])]
        if None in valores:
            continue  # cabecera de un año en curso, sin cifras
        imp_j, imp_i, imp_t, n_j, n_i, n_t = valores
        filas.append((int(m.group(1)), n_j, n_i, n_t, imp_j, imp_i, imp_t))
    if not filas:
        raise ImsersoError("evolución de las nóminas: no se encuentra ninguna fila anual («AÑO aaaa»)")
    return pd.DataFrame(filas, columns=["anio", *SERIES])


def get_evolucion(anios: Iterable[int] | None = None, *, fecha_consulta: str | None = None,
                  sesion: requests.Session | None = None) -> tuple[pd.DataFrame, list[FuenteMeta]]:
    """Pensiones no contributivas (número e importe bruto anual) por tipo, total Estado. `anios`: por defecto, todos."""
    s = sesion or requests.Session()
    urls = buscar(_get(s, PAGINA_PNC, "PNC").text, FICHERO_EVOLUCION)
    if len(urls) != 1:
        raise ImsersoError(f"evolución de las nóminas: se esperaba un enlace a {FICHERO_EVOLUCION} y hay {len(urls)}")
    ancho = parsear_evolucion(_get(s, urls[0], FICHERO_EVOLUCION).content)
    if anios is not None:
        ancho = ancho[ancho["anio"].isin(list(anios))]
    largo = ancho.melt(id_vars="anio", var_name="serie", value_name="valor").rename(columns={"anio": "periodo"})
    df = validar_df(largo[["serie", "periodo", "valor"]])
    hoy = fecha_consulta or date.today().isoformat()
    descripcion = "Evolución de las nóminas de pensiones no contributivas, total Estado (evolpncs.csv)"
    return df, [FuenteMeta(sr, ORGANISMO, descripcion, PAGINA_PNC, hoy) for sr in SERIES]
