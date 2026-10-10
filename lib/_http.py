"""Utilidades HTTP comunes de los fetchers: reintentos con espera exponencial."""

from __future__ import annotations

import time
from typing import Callable, Mapping, Sequence

import requests


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
    """GET con reintentos para fallos de red, 5xx y 429. Otros 4xx lanzan `error_cls` de inmediato."""
    ultimo: Exception | None = None
    for intento in range(reintentos + 1):
        try:
            r = sesion.get(url, params=params, headers=headers, timeout=60)
        except requests.RequestException as e:
            ultimo = e
        else:
            if r.status_code < 400:
                return r
            if r.status_code < 500 and r.status_code != 429:
                raise error_cls(f"{etiqueta}: HTTP {r.status_code}: {mensaje(r)}")
            ultimo = error_cls(f"HTTP {r.status_code}: {mensaje(r)}")
        if intento < reintentos:
            time.sleep(2**intento)
    raise error_cls(f"{etiqueta}: la consulta falló tras {reintentos + 1} intentos: {ultimo}")
