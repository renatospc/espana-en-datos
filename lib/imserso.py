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

- `get_nacionalidad()`: pensionistas no contributivos por nacionalidad en diciembre del último año, del informe en
  PDF «Perfil del pensionista de PNC y del beneficiario de PSPD» (`perfil_pnc_pspd_<año>.pdf`, apartado 1.4,
  «Nacionalidad del pensionista no contributivo»). Solo el último año: la página enlaza el informe vigente y el
  Excel del perfil (`avperfil_pnc_<año>.xlsx`) no trae la nacionalidad. Series `pensionistas_espana`,
  `pensionistas_ue_eee` (otros países de la UE y del Espacio Económico Europeo), `pensionistas_otras` y
  `pensionistas_total` (personas, no pensiones). Verificado el 2026-10-27 con el informe de 2025.

Ejemplo real::

    from lib import imserso

    df, fuentes = imserso.get_evolucion()
    # serie "pensiones_total": número de pensiones no contributivas en la nómina de cada año
    df, fuentes = imserso.get_nacionalidad()
    # series "pensionistas_*": pensionistas por nacionalidad en diciembre del año del informe
"""

from __future__ import annotations

import io
import re
from datetime import date
from typing import Iterable
from urllib.parse import unquote

import pandas as pd
import requests
from pypdf import PdfReader

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


def _nombre(url: str) -> str:
    """Nombre del fichero de un enlace `/documents/…/<nombre>/<uuid>`."""
    partes = unquote(url).split("/")
    return partes[-2] if len(partes) >= 2 else ""


def buscar_patron(html: str, patron: re.Pattern[str]) -> list[str]:
    """Urls absolutas de los enlaces a ficheros cuyo nombre cumple `patron` entero."""
    vistos = []
    for href in re.findall(r'href="([^"]+)"', html):
        href = href.replace("&amp;", "&")
        if patron.fullmatch(_nombre(href)):
            url = BASE + href if href.startswith("/") else href
            if url not in vistos:
                vistos.append(url)
    return vistos


def buscar(html: str, nombre: str) -> list[str]:
    """Urls absolutas de los enlaces a ficheros cuyo nombre es exactamente `nombre` (p. ej. `evolpncs.csv`)."""
    return buscar_patron(html, re.compile(re.escape(nombre)))


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


PERFIL = re.compile(r"perfil_pnc_pspd_(\d{4})\.pdf")
NACIONALIDADES = ("pensionistas_ue_eee", "pensionistas_espana", "pensionistas_otras")
_NUM = re.compile(r"\d{1,3}(?:\.\d{3})*")


def _cifra(s: str) -> int:
    return int(s.replace(".", ""))


def _partir(grupo: str, total: int) -> int:
    """Número de un grupo «número + porcentaje» que la extracción del PDF deja pegado («10.6632,26»): la partición
    cuyo número da ese porcentaje del total."""
    for k in range(1, len(grupo)):
        n, pct = grupo[:k], grupo[k:]
        if _NUM.fullmatch(n) and re.fullmatch(r"\d{1,3},\d{2}", pct):
            if abs(_cifra(n) / total * 100 - float(pct.replace(",", "."))) < 0.006:
                return _cifra(n)
    raise ImsersoError(f"nacionalidad: no se puede leer el grupo {grupo!r}")


def parsear_nacionalidad(texto: str) -> dict[str, int]:
    """Pensionistas por nacionalidad del primer cuadro «TOTAL UE Y EEE / ESPAÑA / OTRAS / TOTAL» del texto (el del
    conjunto de los pensionistas, apartado 1.4); comprueba que las tres nacionalidades suman el total."""
    m = re.search(r"TOTAL UE Y EEE.*?OTRAS\s+TOTAL\s*N\S\s*%\s*N\S\s*%\s*N\S\s*%\s*N\S\s*\n([^\n]+)", texto, re.S)
    if not m:
        raise ImsersoError("nacionalidad: no se encuentra el cuadro «TOTAL UE Y EEE … TOTAL» en el perfil")
    fila = re.sub(r"\s+", "", m.group(1))
    grupos = fila.split("%")
    if len(grupos) != 4 or not _NUM.fullmatch(grupos[3]):
        raise ImsersoError(f"nacionalidad: fila con un formato no reconocido: {m.group(1)!r}")
    total = _cifra(grupos[3])
    valores = dict(zip(NACIONALIDADES, (_partir(g, total) for g in grupos[:3])))
    if sum(valores.values()) != total:
        raise ImsersoError(f"nacionalidad: las nacionalidades suman {sum(valores.values())} y el total es {total}")
    return {**valores, "pensionistas_total": total}


def get_nacionalidad(*, fecha_consulta: str | None = None,
                     sesion: requests.Session | None = None) -> tuple[pd.DataFrame, list[FuenteMeta]]:
    """Pensionistas no contributivos por nacionalidad en diciembre del año del último perfil publicado."""
    s = sesion or requests.Session()
    html = _get(s, PAGINA_PNC, "PNC").text
    # El informe vigente: el de año más reciente entre los enlaces a perfil_pnc_pspd_<año>.pdf
    perfiles = {int(m.group(1)): u for u in buscar_patron(html, PERFIL) if (m := PERFIL.fullmatch(_nombre(u)))}
    if not perfiles:
        raise ImsersoError("nacionalidad: la página no enlaza ningún perfil_pnc_pspd_<año>.pdf")
    anio = max(perfiles)
    url = perfiles[anio]
    lector = PdfReader(io.BytesIO(_get(s, url, f"perfil {anio}").content))
    # El cuadro del conjunto de los pensionistas es el primero: se para en la primera página que lo tiene.
    texto = next((t for p in lector.pages if "UE Y EEE" in (t := p.extract_text() or "")), "")
    valores = parsear_nacionalidad(texto)
    df = validar_df(pd.DataFrame({"serie": list(valores), "periodo": anio, "valor": [float(v) for v in valores.values()]}))
    hoy = fecha_consulta or date.today().isoformat()
    descripcion = (f"Perfil del pensionista de PNC y del beneficiario de PSPD {anio} (PDF), apartado 1.4, "
                   "nacionalidad del pensionista no contributivo (diciembre)")
    return df, [FuenteMeta(sr, ORGANISMO, descripcion, url, hoy) for sr in valores]
