"""Utilidades HTTP comunes de los fetchers: reintentos con espera exponencial.

La API de la OCDE limita las descargas por IP (60 por hora; antes, también 20 por minuto) y bloquea un tiempo a
quien lo supera, y las IP de GitHub Actions las comparten muchos usuarios. Por eso:

- Un 429 (demasiadas peticiones) se reintenta aparte, con esperas largas (`ESPERAS_429`, que cubren casi una hora)
  o lo que diga `Retry-After` si es más.
- Las peticiones reales a `sdmx.oecd.org` se espacian al menos `INTERVALO_MIN` segundos.
- Con la variable de entorno `ESPANAENDATOS_CACHE_HTTP=<carpeta>` (la CI la activa), las respuestas correctas se
  guardan en esa carpeta y las peticiones idénticas de otros notebooks de la misma ejecución no vuelven a la red.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Callable, Mapping, Sequence
from urllib.parse import urlsplit

import requests

ESPERAS_429 = (60, 120, 300, 600, 900, 1200)  # segundos entre reintentos tras un 429 (unos 53 minutos en total)
ESPERA_MAX_429 = 3600
INTERVALO_MIN = {"sdmx.oecd.org": 3.5}  # segundos entre peticiones reales al mismo servidor
VARIABLE_CACHE = "ESPANAENDATOS_CACHE_HTTP"

_ultima_peticion: dict[str, float] = {}


def _espera_429(r: requests.Response, n: int) -> float:
    propia = ESPERAS_429[min(n, len(ESPERAS_429) - 1)]
    valor = str(getattr(r, "headers", {}).get("Retry-After", "")).strip()
    return min(max(int(valor), propia), ESPERA_MAX_429) if valor.isdigit() else propia


def _espaciar(sesion: requests.Session, url: str) -> None:
    """Espera lo necesario para no pedir al mismo servidor más a menudo que `INTERVALO_MIN` (solo sesiones reales)."""
    host = urlsplit(url).hostname or ""
    if host not in INTERVALO_MIN or not isinstance(sesion, requests.Session):
        return
    pendiente = _ultima_peticion.get(host, -INTERVALO_MIN[host]) + INTERVALO_MIN[host] - time.monotonic()
    if pendiente > 0:
        time.sleep(pendiente)
    _ultima_peticion[host] = time.monotonic()


def _fichero_cache(url: str, params, headers) -> Path | None:
    carpeta = os.environ.get(VARIABLE_CACHE)
    if not carpeta:
        return None
    clave = json.dumps([url, sorted((params.items() if isinstance(params, Mapping) else params) or []), sorted((headers or {}).items())], ensure_ascii=False)
    return Path(carpeta) / (hashlib.sha256(clave.encode()).hexdigest() + ".json")


def _de_cache(f: Path, url: str) -> requests.Response:
    datos = json.loads(f.read_text(encoding="utf-8"))
    r = requests.Response()
    r.status_code, r.url, r.encoding = 200, url, datos["encoding"]
    r.headers["Content-Type"] = datos["content_type"]
    r._content = bytes.fromhex(datos["contenido"])
    return r


def _a_cache(f: Path, r: requests.Response) -> None:
    f.parent.mkdir(parents=True, exist_ok=True)
    datos = {"encoding": r.encoding, "content_type": r.headers.get("Content-Type", ""), "contenido": r.content.hex()}
    f.write_text(json.dumps(datos), encoding="utf-8")


def pedir(
    sesion: requests.Session,
    url: str,
    params: Sequence[tuple[str, str]] | Mapping[str, str] | None,
    *,
    error_cls: type[Exception],
    etiqueta: str,
    mensaje: Callable[[requests.Response], str],
    headers: Mapping[str, str] | None = None,
    reintentos: int = 2,
) -> requests.Response:
    """GET con reintentos para fallos de red y 5xx, y reintentos aparte, con esperas largas, para 429.

    Otros 4xx lanzan `error_cls` de inmediato.
    """
    cache = _fichero_cache(url, params, headers)
    if cache and cache.exists():
        return _de_cache(cache, url)
    ultimo: Exception | None = None
    intento = n429 = 0
    while True:
        _espaciar(sesion, url)
        try:
            r = sesion.get(url, params=params, headers=headers, timeout=60)
        except requests.RequestException as e:
            ultimo = e
        else:
            if r.status_code < 400:
                if cache and isinstance(r, requests.Response):
                    _a_cache(cache, r)
                return r
            if r.status_code < 500 and r.status_code != 429:
                raise error_cls(f"{etiqueta}: HTTP {r.status_code}: {mensaje(r)}")
            ultimo = error_cls(f"HTTP {r.status_code}: {mensaje(r)}")
            if r.status_code == 429 and n429 < len(ESPERAS_429):
                time.sleep(_espera_429(r, n429))
                n429 += 1
                continue
        if intento >= reintentos:
            break
        time.sleep(2**intento)
        intento += 1
    raise error_cls(f"{etiqueta}: la consulta falló tras {intento + n429 + 1} intentos: {ultimo}")
