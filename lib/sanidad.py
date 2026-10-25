"""Fetcher del Ministerio de Sanidad: EGSP, SIAE, Barómetro Sanitario e Indicadores Clave del SNS (INCLASNS).

Mecanismos verificados el 2026-10-24:

- **Estadística de Gasto Sanitario Público (EGSP)**: un Excel (`.xls`, formato BIFF) con la serie 2002-último año,
  una hoja por tabla («Tabla 1.2», «Tabla 3.4.01»…). `egsp(hoja)`. La serie 1988-2005, con la metodología anterior,
  en otro Excel: `egsp_1988_2005(hoja)`.
- **Estadística de Centros Sanitarios de Atención Especializada (SIAE)**: Excel (`.xlsx`) de evolución y por
  comunidades de cada año en `docs/TablasSIAE<año>/`. `siae(fichero, hoja)`.
- **Barómetro Sanitario** (Ministerio de Sanidad y CIS): Excel con la serie de las principales variables por
  comunidad desde 1998 (`barometro(hoja)`) y Excel de resultados de cada oleada, con una hoja «Marginales» en la que
  cada pregunta («Pregunta 12») va seguida de su enunciado, una fila por respuesta con su porcentaje y la base «(N)»
  (`barometro_pregunta(url, numero)`).
- **INCLASNS**: la aplicación https://inclasns.sanidad.gob.es/ sirve cada indicador como una tabla HTML (servicio
  `table/data`, el mismo que usa su botón de exportar), con el valor completo en el atributo `data-order` de cada
  celda. `inclasns(indicador)`.

Las tablas de la EGSP, la SIAE y el Barómetro tienen la misma forma: bloques con una fila de años (columnas) y debajo
una fila por concepto, con su nombre en la primera celda de texto. `tabla_anual` las convierte en filas `bloque,
grupo, concepto, periodo, valor`:

- `bloque`: el texto de las filas sin datos que hay antes de la fila de años (título de la tabla, clasificación,
  comunidad…), unido con « · ».
- `grupo`: el último concepto en mayúsculas del bloque (p. ej. el sector «COMUNIDADES AUTÓNOMAS» en la tabla 1.4 de la
  EGSP), para distinguir conceptos que se repiten en cada grupo.
- `periodo`: el año de la cabecera (`2023(*)` → 2023, `2014.0` → 2014). Las celdas sin número («-», vacías) son NaN.

Las filas sin nombre (en la EGSP, el porcentaje de la fila anterior) se descartan.

Ejemplo real::

    from lib import sanidad

    tabla, url = sanidad.egsp("Tabla 1.2")
    funcional = tabla[tabla["bloque"].str.contains("FUNCIONAL")]
    esperas, fuentes = sanidad.inclasns(160)   # tiempo medio de espera quirúrgica, España y comunidades
"""

from __future__ import annotations

import html
import io
import json
import re
from datetime import date
from html.parser import HTMLParser

import pandas as pd
import requests

from ._http import pedir
from .tipos import FuenteMeta, validar_df

ORGANISMO = "Ministerio de Sanidad"
CABECERA = {"User-Agent": "Mozilla/5.0 (compatible; EspanaenDatos)"}

BASE = "https://www.sanidad.gob.es/estadEstudios/estadisticas"
URL_EGSP = f"{BASE}/inforRecopilaciones/gastoSanitario2005/tablasEstEGSP/egspGastoReal..xls"
URL_EGSP_1988 = f"{BASE}/sisInfSanSNS/pdf/Serie_1988_2005_Nuevo.xls"
URL_SIAE = BASE + "/docs/TablasSIAE{anio}/{fichero}"
URL_BAROMETRO = f"{BASE}/BarometroSanitario/Barom_Sanit_2025/Totales/BS_1998-2025_Principales_variables_CCAA.xlsx"
URL_BAROMETRO_2026_1 = f"{BASE}/BarometroSanitario/Barom_Sanit_2026/BS_2026_CIS_1_OLA_3551.xlsx"
URL_INCLASNS = "https://inclasns.sanidad.gob.es/"

_ANIO = re.compile(r"^\s*((?:19|20)\d\d)(?:\.0+)?\s*(?:\(\*\))?\s*$")


class SanidadError(RuntimeError):
    """Error de un servidor del Ministerio de Sanidad o fichero con un formato no reconocido."""


# ---------- Tablas anuales en Excel (EGSP, SIAE, Barómetro) ----------


def _anio(v) -> int | None:
    if isinstance(v, (int, float)) and not pd.isna(v) and float(v).is_integer() and 1900 < v < 2100:
        return int(v)
    m = _ANIO.match(str(v)) if isinstance(v, str) else None
    return int(m.group(1)) if m else None


def _texto(v) -> str | None:
    if isinstance(v, str) and v.strip() and v.strip() != "-" and _anio(v) is None:
        return " ".join(v.split())
    return None


def tabla_anual(hoja: pd.DataFrame) -> pd.DataFrame:
    """Filas `bloque, grupo, concepto, periodo, valor` de una hoja leída sin cabecera (ver el docstring del módulo)."""
    filas = []
    titulo: list[str] = []
    columnas: dict[int, int] = {}
    bloque, grupo = "", None
    for i in range(len(hoja)):
        celdas = list(hoja.iloc[i])
        años = {j: a for j, v in enumerate(celdas) if (a := _anio(v)) is not None}
        if len(años) >= 2:
            titulo += [t for j, v in enumerate(celdas) if j not in años and (t := _texto(v))]
            columnas, bloque, grupo, titulo = años, " · ".join(titulo), None, []
            continue
        primera = min(columnas) if columnas else len(celdas)
        nombre = next((t for v in celdas[:primera] if (t := _texto(v))), None)
        valores = {a: pd.to_numeric(celdas[j], errors="coerce") for j, a in columnas.items() if j < len(celdas)}
        con_dato = any(pd.notna(v) for v in valores.values())
        if nombre and con_dato and columnas:
            if nombre.upper() == nombre and re.search(r"[A-ZÁÉÍÓÚÑ]", nombre):
                grupo = nombre
            filas += [(bloque, grupo, nombre, a, float(v)) for a, v in valores.items()]
        elif not con_dato:
            textos = [t for v in celdas if (t := _texto(v)) and t not in ("Índice", "INDICE", "ÍNDICE")]
            titulo += textos
    return pd.DataFrame(filas, columns=["bloque", "grupo", "concepto", "periodo", "valor"])


def _excel(url: str, etiqueta: str, sesion: requests.Session | None, reintentos: int) -> bytes:
    r = pedir(
        sesion or requests.Session(), url, None,
        error_cls=SanidadError, etiqueta=etiqueta, mensaje=lambda r: r.text[:200], headers=CABECERA, reintentos=reintentos,
    )
    return r.content


def _hoja(contenido: bytes, hoja: str, etiqueta: str) -> pd.DataFrame:
    try:
        libro = pd.ExcelFile(io.BytesIO(contenido))
    except Exception as e:  # xlrd y openpyxl lanzan varios tipos según el fallo
        raise SanidadError(f"{etiqueta}: no es un Excel legible") from e
    if hoja not in libro.sheet_names:
        raise SanidadError(f"{etiqueta}: no tiene la hoja {hoja!r}; hojas: {', '.join(libro.sheet_names)}")
    return libro.parse(hoja, header=None)


def egsp(hoja: str, *, sesion: requests.Session | None = None, reintentos: int = 2) -> tuple[pd.DataFrame, str]:
    """Tabla de la EGSP (p. ej. `"Tabla 1.2"`) como filas `bloque, grupo, concepto, periodo, valor` y la URL del Excel.

    Los importes están en miles de euros corrientes; las cifras de los dos últimos años son provisionales.
    """
    t = tabla_anual(_hoja(_excel(URL_EGSP, "EGSP", sesion, reintentos), hoja, f"EGSP, {hoja}"))
    if t.empty:
        raise SanidadError(f"EGSP, {hoja}: no se encuentra ninguna fila de años")
    return t, URL_EGSP


def egsp_1988_2005(hoja: str, *, sesion: requests.Session | None = None, reintentos: int = 2) -> tuple[pd.DataFrame, str]:
    """Tabla de la serie 1988-2005 de la EGSP, con la metodología anterior (p. ej. `"tabla 3"`), y la URL del Excel."""
    t = tabla_anual(_hoja(_excel(URL_EGSP_1988, "EGSP 1988-2005", sesion, reintentos), hoja, f"EGSP 1988-2005, {hoja}"))
    if t.empty:
        raise SanidadError(f"EGSP 1988-2005, {hoja}: no se encuentra ninguna fila de años")
    return t, URL_EGSP_1988


def siae(fichero: str, hoja: str, *, anio: int = 2023, sesion: requests.Session | None = None,
         reintentos: int = 2) -> tuple[pd.DataFrame, str]:
    """Tabla de la SIAE (p. ej. `"Datos_economicos_Evolucion_2014-2023.xlsx"`, `"TABLA 4.1"`) y la URL del Excel.

    `anio` es el de la carpeta de publicación (`docs/TablasSIAE<anio>/`).
    """
    url = URL_SIAE.format(anio=anio, fichero=fichero)
    t = tabla_anual(_hoja(_excel(url, fichero, sesion, reintentos), hoja, f"SIAE, {fichero}, {hoja}"))
    if t.empty:
        raise SanidadError(f"SIAE, {fichero}, {hoja}: no se encuentra ninguna fila de años")
    return t, url


def barometro(hoja: str, *, sesion: requests.Session | None = None, reintentos: int = 2) -> tuple[pd.DataFrame, str]:
    """Hoja (p. ej. `"P 4"`) de la serie de principales variables del Barómetro Sanitario, por comunidad desde 1998."""
    t = tabla_anual(_hoja(_excel(URL_BAROMETRO, "Barómetro Sanitario", sesion, reintentos), hoja, f"Barómetro, {hoja}"))
    if t.empty:
        raise SanidadError(f"Barómetro, {hoja}: no se encuentra ninguna fila de años")
    return t, URL_BAROMETRO


def parsear_pregunta(hoja: pd.DataFrame, numero: int) -> tuple[str, pd.Series, int]:
    """(enunciado, porcentaje por respuesta, base N) de la pregunta `numero` de una hoja «Marginales»."""
    col0 = [str(v).strip() if pd.notna(v) else "" for v in hoja.iloc[:, 0]]
    inicio = next((i for i, v in enumerate(col0) if v == f"Pregunta {numero}"), None)
    if inicio is None:
        raise SanidadError(f"Barómetro: no se encuentra «Pregunta {numero}»")
    enunciado = " ".join(col0[inicio + 1].split())
    respuestas = {}
    for i in range(inicio + 2, len(hoja)):
        nombre, valor = col0[i], pd.to_numeric(hoja.iat[i, 1], errors="coerce")
        if nombre == "(N)":
            return enunciado, pd.Series(respuestas, dtype=float), int(valor)
        if not nombre or pd.isna(valor):
            break
        respuestas[" ".join(nombre.split())] = float(valor)
    raise SanidadError(f"Barómetro: la «Pregunta {numero}» no termina con su base «(N)»")


def barometro_pregunta(url: str, numero: int, *, sesion: requests.Session | None = None,
                       reintentos: int = 2) -> tuple[str, pd.Series, int]:
    """Pregunta de la hoja «Marginales» del Excel de una oleada del Barómetro Sanitario (p. ej. `URL_BAROMETRO_2026_1`)."""
    hoja = _hoja(_excel(url, "Barómetro Sanitario", sesion, reintentos), "Marginales", "Barómetro, Marginales")
    return parsear_pregunta(hoja, numero)


# ---------- INCLASNS ----------

# Comunidades de INCLASNS: el código entre paréntesis del nombre (`Andalucía (AN)`) es el de ISO 3166-2:ES.
_AREA = re.compile(r"\((ES|[A-Z]{2})\)\s*$")


class _Tabla(HTMLParser):
    """Filas de una tabla HTML: texto de cada `th`/`td` y su `data-order`."""

    def __init__(self) -> None:
        super().__init__()
        self.filas: list[list[tuple[str, str | None, str]]] = []
        self._celda: list[str] | None = None
        self._orden: str | None = None
        self._tipo = ""

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.filas.append([])
        elif tag in ("td", "th"):
            self._celda, self._orden, self._tipo = [], dict(attrs).get("data-order"), tag

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._celda is not None and self.filas:
            self.filas[-1].append((self._tipo, self._orden, "".join(self._celda).strip()))
            self._celda = None

    def handle_data(self, data):
        if self._celda is not None:
            self._celda.append(data)


def parsear_inclasns(texto: str, indicador: int) -> pd.DataFrame:
    """Filas `serie, periodo, valor` de la respuesta de `table/data` (tabla con comunidades en filas y años en columnas)."""
    try:
        tabla = json.loads(texto)
    except ValueError:
        tabla = texto
    if not isinstance(tabla, str) or "<table" not in tabla:
        raise SanidadError(f"INCLASNS {indicador}: la respuesta no es una tabla")
    p = _Tabla()
    p.feed(html.unescape(tabla) if "&lt;" in tabla else tabla)
    años = [int(t) for fila in p.filas for tipo, _, t in fila if tipo == "th" and re.fullmatch(r"(19|20)\d\d", t)]
    filas = []
    for fila in p.filas:
        tds = [c for c in fila if c[0] == "td"]
        if not tds:
            continue
        m = _AREA.search(tds[0][2])
        if not m:
            raise SanidadError(f"INCLASNS {indicador}: territorio no reconocido: {tds[0][2]!r}")
        serie = "espana" if m.group(1) == "ES" else f"ES-{m.group(1)}"
        if len(tds) - 1 != len(años):
            raise SanidadError(f"INCLASNS {indicador}: {len(tds) - 1} celdas para {len(años)} años")
        for (_, orden, _), a in zip(tds[1:], años):
            filas.append((serie, a, float(orden) if orden not in (None, "") else float("nan")))
    if not filas:
        raise SanidadError(f"INCLASNS {indicador}: la tabla no tiene filas")
    return pd.DataFrame(filas, columns=["serie", "periodo", "valor"])


def _codigos(pagina: str, clase: str) -> dict[str, str]:
    """{valor: etiqueta} de las casillas `clase` (areaCode, year, sex) de la página principal."""
    patron = rf'class="{clase}" id="variableState-{clase}-(\d+)"[^>]*/>\s*<label[^>]*>([^<]*)</label>'
    return {v: html.unescape(e).strip() for v, e in re.findall(patron, pagina)}


def inclasns(
    indicador: int,
    *,
    desde: int = 1976,
    fecha_consulta: str | None = None,
    sesion: requests.Session | None = None,
    reintentos: int = 2,
) -> tuple[pd.DataFrame, list[FuenteMeta]]:
    """Indicador de INCLASNS (número de su ficha) para España y todas las comunidades, ambos sexos, todos los años.

    Devuelve `(DataFrame serie/periodo/valor, fuentes)`: `espana` y una serie por código ISO 3166-2:ES. Los códigos de
    años y territorios se leen de la página principal, así que los años nuevos entran solos.
    """
    s = sesion or requests.Session()
    kw = dict(error_cls=SanidadError, mensaje=lambda r: r.text[:200], headers=CABECERA, reintentos=reintentos)
    pagina = pedir(s, URL_INCLASNS + "main.html", None, etiqueta="INCLASNS", **kw).text
    areas, años, sexos = _codigos(pagina, "areaCode"), _codigos(pagina, "year"), _codigos(pagina, "sex")
    años = {v: e for v, e in años.items() if re.fullmatch(r"(19|20)\d\d", e)}
    total = next((v for v, e in sexos.items() if e == "Total"), None)
    if not areas or not años or total is None:
        raise SanidadError("INCLASNS: no se encuentran los códigos de territorios, años o sexo en la página principal")
    params = {
        "pagination": "indicator", "rows": "areaCode", "columns": "year", "sex": total,
        "areaCode": ",".join(areas), "year": ",".join(años), "nse": "", "nsi": "", "nsc": "", "show": "values",
        "indicator": str(indicador), "indicators": str(indicador),
    }
    r = pedir(s, URL_INCLASNS + "table/data", params, etiqueta=f"INCLASNS {indicador}", **kw)
    obs = parsear_inclasns(r.text, indicador)
    df = validar_df(obs[obs["periodo"] >= desde].dropna(subset=["valor"]).reset_index(drop=True))
    hoy = fecha_consulta or date.today().isoformat()
    fuentes = [FuenteMeta(sr, ORGANISMO, f"INCLASNS, indicador {indicador}", URL_INCLASNS, hoy) for sr in df["serie"].unique()]
    return df, fuentes
