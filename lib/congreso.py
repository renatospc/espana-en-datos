"""Votaciones del Pleno del Congreso: voto de cada partido a partir de los datos abiertos.

Datos abiertos: https://www.congreso.es/es/opendata/votaciones. Cada votación electrónica tiene un JSON
(`/webpublica/opendata/votaciones/Leg15/Sesion<NNN>/<AAAAMMDD>/Votacion<NNN>/VOT_<marca>.json`) con
`informacion` (sesión, número, textos), `totales` (`afavor`, `enContra`, `abstenciones`, `noVotan`) y
`votaciones[]` (`diputado` «Apellidos, Nombre», `grupo` y `voto`: «Sí», «No», «Abstención» o «No vota»).
Mecanismo verificado el 2026-10-10 con las votaciones de la XV legislatura; el fichero puede llevar BOM y el
servidor responde 403 al agente por defecto de `requests`, así que la petición lleva un `User-Agent` propio.

El voto de un partido es el sentido mayoritario de sus diputados que votaron; `dividido` si empatan los
sentidos más votados y `no_vota` si no votó ninguno (METODOLOGIA §4.2). Los partidos con grupo propio se
identifican por el código de grupo (`GRUPOS`) y los del Grupo Mixto por el nombre del diputado
(`DIPUTADOS`), que también cubre a Podemos antes de pasar al Mixto en diciembre de 2023. Los diputados del
Mixto sin partido en `global.json` (p. ej. los que dejaron su grupo sin formar partido) no cuentan.

Las votaciones por llamamiento (p. ej. la convalidación de los Reales Decretos-leyes 26/2026 y 27/2026,
2-10-2026) no están en los datos abiertos: su fuente es el Diario de Sesiones, no llevan `url_datos` y sus votos
los cuenta `lib/posiciones.py` en el PDF del Diario (`descargar_pdf`). Si cambia la composición de los grupos,
actualiza `GRUPOS` y `DIPUTADOS`.

Uso, desde `research/` (comprueba los votos de `posiciones.json` contra los datos abiertos; necesita red)::

    uv run python -m lib.congreso comprobar temas/vivienda/posiciones.json
"""

from __future__ import annotations

import json
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping

import requests

from ._http import pedir

RAIZ = Path(__file__).resolve().parent.parent
GLOBAL = RAIZ / "global.json"

# Código de grupo en los datos abiertos → partido de global.json.
GRUPOS = {
    "GS": "psoe",
    "GP": "pp",
    "GVOX": "vox",
    "GSUMAR": "sumar",
    "GR": "erc",
    "GJxCAT": "junts",
    "GEH Bildu": "bildu",
    "GV (EAJ-PNV)": "pnv",
}

# Diputados cuyo partido no es el de su grupo (Grupo Mixto), tal como los escriben los datos abiertos.
DIPUTADOS = {
    "Belarra Urteaga, Ione": "podemos",
    "Sánchez Serna, Javier": "podemos",
    "Santana Perera, Noemí": "podemos",
    "Velarde Gómez, Martina": "podemos",
    "Verstrynge Revuelta, Lilith": "podemos",  # figura en el Grupo Mixto en las votaciones de enero de 2024
    "Rego Candamil, Néstor": "bng",
    "Valido García, Cristina": "cc",
    "Catalán Higueras, Alberto": "upn",
}

VOTOS = {"Sí": "si", "No": "no", "Abstención": "abstencion"}


def _cabecera() -> dict[str, str]:
    """El servidor del Congreso rechaza (403) el agente por defecto de requests; se identifica el proyecto."""
    proyecto = json.loads(GLOBAL.read_text(encoding="utf-8"))["proyecto"]
    # Las cabeceras HTTP deben ser ASCII: «España en Datos» → «EspanaenDatos».
    nombre = unicodedata.normalize("NFKD", proyecto["nombre"]).encode("ascii", "ignore").decode().replace(" ", "")
    return {"User-Agent": f"Mozilla/5.0 (compatible; {nombre}; +https://{proyecto['dominio']})"}


class CongresoError(RuntimeError):
    pass


def partido_de(diputado: str, grupo: str) -> str | None:
    """Partido de global.json al que corresponde un voto, o None si no cuenta para ninguno."""
    return DIPUTADOS.get(diputado) or GRUPOS.get(grupo)


def voto_partido(votos: Iterable[str]) -> str:
    """Sentido mayoritario de una lista de votos tal como vienen en los datos abiertos («Sí», «No vota»…)."""
    c = Counter(VOTOS[v] for v in votos if v in VOTOS)
    if not c:
        return "no_vota"
    (primero, n), *resto = c.most_common()
    if resto and resto[0][1] == n:
        return "dividido"
    return primero


def votos_por_partido(datos: Mapping, partidos: Iterable[str]) -> dict[str, str]:
    """Voto de cada partido en una votación (JSON de datos abiertos ya leído)."""
    por_partido: dict[str, list[str]] = {p: [] for p in partidos}
    for d in datos.get("votaciones", []):
        p = partido_de(d.get("diputado", ""), d.get("grupo", ""))
        if p in por_partido:
            por_partido[p].append(d.get("voto", ""))
    return {p: voto_partido(v) for p, v in por_partido.items()}


def resultado(datos: Mapping) -> str:
    """`aprobada` si hay más votos a favor que en contra (mayoría simple)."""
    t = datos.get("totales", {})
    return "aprobada" if int(t.get("afavor", 0)) > int(t.get("enContra", 0)) else "rechazada"


def descargar(url: str, sesion: requests.Session | None = None) -> dict:
    r = pedir(
        sesion or requests.Session(),
        url,
        None,
        error_cls=CongresoError,
        etiqueta=url,
        mensaje=lambda r: r.text[:200],
        headers=_cabecera(),
    )
    return json.loads(r.content.decode("utf-8-sig"))


def descargar_pdf(url: str, sesion: requests.Session | None = None) -> bytes:
    """PDF de un Diario de Sesiones (sin el `#page=` de la dirección)."""
    url = url.split("#")[0]
    r = pedir(
        sesion or requests.Session(),
        url,
        None,
        error_cls=CongresoError,
        etiqueta=url,
        mensaje=lambda r: r.text[:200],
        headers=_cabecera(),
    )
    return r.content


def partidos_globales() -> list[str]:
    return [p["id"] for p in json.loads(GLOBAL.read_text(encoding="utf-8"))["partidos"]]


def comprobar(posiciones: Path, sesion: requests.Session | None = None) -> tuple[list[str], list[str]]:
    """Compara votos y resultado de cada votación con `url_datos` con los datos abiertos.

    Devuelve (diferencias, votaciones sin comprobación automática).
    """
    partidos = partidos_globales()
    pos = json.loads(Path(posiciones).read_text(encoding="utf-8"))
    diferencias: list[str] = []
    manuales: list[str] = []
    for m in pos["medidas"]:
        for v in m.get("votaciones", []):
            ruta = f"{m['medida_id']}/{v['id']}"
            if "url_datos" not in v:
                manuales.append(ruta)
                continue
            datos = descargar(v["url_datos"], sesion)
            esperado = votos_por_partido(datos, partidos)
            for p in partidos:
                if v["votos"].get(p) != esperado[p]:
                    diferencias.append(f"{ruta}: {p} = {v['votos'].get(p)!r}, datos abiertos = {esperado[p]!r}")
            if v["resultado"] != resultado(datos):
                diferencias.append(f"{ruta}: resultado = {v['resultado']!r}, datos abiertos = {resultado(datos)!r}")
    return diferencias, manuales


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "comprobar":
        print("Uso: python -m lib.congreso comprobar temas/<slug>/posiciones.json", file=sys.stderr)
        return 2
    diferencias, manuales = comprobar(Path(argv[1]))
    for d in diferencias:
        print("DIFERENCIA", d)
    for m in manuales:
        print("SIN DATOS ABIERTOS (comprobar con el Diario de Sesiones):", m)
    print(f"{len(diferencias)} diferencias")
    return 1 if diferencias else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
