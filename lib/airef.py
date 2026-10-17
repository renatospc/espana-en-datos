"""Texto de los informes en PDF de la AIReF (Autoridad Independiente de Responsabilidad Fiscal).

Web: https://www.airef.es/es/centro-documental/ — la AIReF no publica sus proyecciones de gasto en pensiones en un
fichero de datos, solo en el texto y los gráficos de sus informes en PDF. `get_texto(url)` descarga el PDF y devuelve
su texto (`pypdf`), con los espacios normalizados y los números partidos por la extracción recompuestos («202 5» →
«2025», «16, 3» → «16,3»), para que el notebook localice con una expresión regular la frase que contiene cada cifra.
Mecanismo verificado el 2026-10-16 con el Estudio de evaluación de la regla de gasto de pensiones (29-5-2026).

Ejemplo real::

    from lib import airef

    texto, fuente = airef.get_texto(airef.ESTUDIO_REGLA_GASTO_2026, serie="airef")

El servidor de la AIReF no envía el certificado intermedio de la FNMT: se usa `sesion_fnmt()` de lib/_http.py.
"""

from __future__ import annotations

import io
import re
from datetime import date

import requests
from pypdf import PdfReader

from ._http import pedir, sesion_fnmt
from .tipos import FuenteMeta

ORGANISMO = "AIReF"
ESTUDIO_REGLA_GASTO_2026 = "https://www.airef.es/wp-content/uploads/2026/05/Pensiones/Estudio_Regla_Gasto_Pensiones-2026.pdf"
CABECERA = {"User-Agent": "Mozilla/5.0 (compatible; EspanaenDatos)"}


class AirefError(RuntimeError):
    """Error de la web de la AIReF o PDF ilegible."""


def normalizar(texto: str) -> str:
    """Espacios simples y números recompuestos tras la extracción del PDF."""
    t = re.sub(r"\s+", " ", texto)
    t = re.sub(r"(?<=\d) (?=\d)", "", t)  # «202 5» → «2025»
    t = re.sub(r"(?<=\d), (?=\d)", ",", t)  # «16, 3» → «16,3»
    return t


def get_texto(url: str, *, serie: str = "airef", fecha_consulta: str | None = None,
              sesion: requests.Session | None = None) -> tuple[str, FuenteMeta]:
    """Texto normalizado de un PDF de la AIReF y su `FuenteMeta`."""
    r = pedir(sesion or sesion_fnmt(), url, None, error_cls=AirefError, etiqueta=url.rsplit("/", 1)[-1],
              mensaje=lambda r: r.text[:200], headers=CABECERA)
    try:
        lector = PdfReader(io.BytesIO(r.content))
        texto = "\n".join(p.extract_text() or "" for p in lector.pages)
    except Exception as e:  # noqa: BLE001
        raise AirefError(f"{url}: PDF ilegible") from e
    if not texto.strip():
        raise AirefError(f"{url}: el PDF no tiene texto")
    hoy = fecha_consulta or date.today().isoformat()
    return normalizar(texto), FuenteMeta(serie, ORGANISMO, url.rsplit("/", 1)[-1], url, hoy)
