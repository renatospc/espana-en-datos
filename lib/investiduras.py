"""Comprueba los votos de las investiduras del Congreso de `global.json` contándolos en el Diario de Sesiones.

Las votaciones de investidura son por llamamiento y no están en los datos abiertos. Cada votación del
Congreso de `investiduras[].votaciones[]` lleva `llamamiento`: `pdf` (el Diario de Sesiones), `paginas`
(primera y última de las listas de votos), `referencias` (JSON de datos abiertos de votaciones de la
legislatura, que dan el grupo de cada diputado; se juntan porque algún diputado dejó el escaño antes de la
siguiente votación electrónica) e `inicio` y `fin` (textos que abren y cierran el tramo). El voto de cada
partido se cuenta con `posiciones.contar_llamamiento`, igual que en las posiciones (METODOLOGIA §4.2), y
`comprobar` falla si no coincide con el escrito en `global.json` o si hay diputados sin identificar.

Las investiduras autonómicas no llevan `llamamiento`: su voto por grupo se toma del Diario de Sesiones o de la
nota oficial de cada parlamento (decisión humana del 2026-10-27, en pending.md).

Uso, desde `research/` (necesita red y `pdftotext`; `--cache` guarda los JSON y los PDF descargados)::

    uv run python -m lib.investiduras comprobar [--cache DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, Mapping

from . import congreso
from .posiciones import contar_llamamiento, descargador, descargador_llamamiento

RAIZ = Path(__file__).resolve().parent.parent


def comprobar(
    global_json: Mapping,
    obtener_json: Callable[[str], dict],
    obtener_llamamiento: Callable[[Mapping], str],
) -> list[str]:
    """Diferencias entre los votos escritos y los contados en cada votación con `llamamiento`."""
    partidos = [p["id"] for p in global_json["partidos"]]
    problemas = []
    for inv in global_json.get("investiduras", []):
        for v in inv["votaciones"]:
            ll = v.get("llamamiento")
            if not ll:
                continue
            ruta = f"{inv['id']} {v['fecha']}"
            roster = [d for url in ll["referencias"] for d in obtener_json(url).get("votaciones", [])]
            contados, _, sin_casar = contar_llamamiento(obtener_llamamiento(ll), {"votaciones": roster}, partidos)
            if sin_casar:
                problemas.append(f"{ruta}: diputados sin identificar: {', '.join(sin_casar)}")
            escritos = {x["partido_id"]: x["voto"] for x in v["votos"] if x.get("partido_id")}
            for p in partidos:
                if escritos.get(p, "no_vota") != contados[p]:
                    problemas.append(f"{ruta}: {p} escrito {escritos.get(p, '(sin voto)')}, contado {contados[p]}")
    return problemas


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m lib.investiduras", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="orden", required=True)
    c = sub.add_parser("comprobar")
    c.add_argument("--cache", type=Path)
    args = ap.parse_args(argv)
    global_json = json.loads(congreso.GLOBAL.read_text(encoding="utf-8"))
    problemas = comprobar(
        global_json,
        obtener_json=descargador(args.cache),
        obtener_llamamiento=descargador_llamamiento(args.cache / "diarios" if args.cache else None),
    )
    for x in problemas:
        print("DIFERENCIA", x)
    n = sum(1 for i in global_json.get("investiduras", []) for v in i["votaciones"] if v.get("llamamiento"))
    print(f"{n} votaciones por llamamiento, {len(problemas)} diferencias")
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
