"""Ensambla `temas/<slug>/posiciones.json` desde los ficheros de trabajo de la investigación (METODOLOGIA §4).

Entradas, en `temas/<slug>/posiciones/`:

- `programa/<partido_id>.json`: posición del partido según su programa y sus documentos propios (§4.1 y
  §4.2). Lleva `documentos` (programas consultados: `fichero_txt`, `titulo`, `url`, `fecha`),
  `argumento_sin_posicion` (frase fija cuando ningún documento trata la medida) y `medidas.<medida_id>`
  con `posicion`, `argumento`, `fuentes` (de tipo `programa` o `comunicado`), `fecha`, `legislatura`,
  `cita_textual` (frase literal), `fichero_txt` y `pagina` (página del PDF del programa), `busquedas`,
  `nota` y, si el grupo del partido tiene una iniciativa sobre la medida en el Congreso, `iniciativa` (la
  más reciente: `sentido`, `alcance`, `argumento`, `cita_textual`, `fuentes` de tipo `iniciativa` o
  `diario_sesiones`, `fecha` y `legislatura`), que va aparte de la posición según el programa.
- `votaciones/<medida_id>.json`: votaciones del Pleno sobre la medida, de la más reciente a la más antigua
  (§4.2), hasta cuatro con `alcance` `especifica` (su objeto principal es la medida; es el valor por
  defecto) y hasta cuatro `amplia` (textos que la incluyen con otras materias), con `id`, `titulo`,
  `descripcion`, `sentido`, `alcance`, `fecha`,
  `legislatura`, `resultado`, `expediente`, `sesion`, `numero`, `url_json`, `url_pdf`, `url_ficha` y
  `diario_sesiones` (página del debate); las votaciones por llamamiento, sin datos abiertos, llevan
  `votos_llamamiento` (contados con `contar_llamamiento`) y `metodo_votos`. `descartadas` recoge las que no
  cumplen la regla, con su motivo.

Salida: por medida, la posición según el programa de cada partido (en `sin_posicion`, con la frase fija del
partido y los documentos consultados como fuentes, §4.1), las iniciativas de los partidos que la tienen y las
votaciones con el voto de cada partido,
calculado con `lib/congreso.py` a partir de los datos abiertos. Avisa de citas que no están en su página
(si se dan los textos de los programas), resultados que no coinciden con los datos abiertos, partidos sin
ningún diputado en una votación, más de cuatro votaciones o mal ordenadas, textos de más de 300
caracteres y valores o tipos de fuente no admitidos. Después, `python -m lib.congreso comprobar` vuelve a
comprobar los votos de `posiciones.json`.

Uso, desde `research/` (necesita red para los datos abiertos; `--cache` guarda los JSON descargados)::

    uv run python -m lib.posiciones ensamblar fiscalidad [--escribir] [--programas DIR] [--cache DIR]
    uv run python -m lib.posiciones extraer-programa programa.pdf DIR/psoe-2023.txt
    uv run python -m lib.posiciones llamamiento DS.pdf PAG_INI PAG_FIN VOT_REF.json "INICIO" "FIN"

`--programas` es la carpeta con los textos de los programas (`fichero_txt`), extraídos con
`extraer-programa` de los PDF oficiales; sin ella no se comprueban las citas. Los textos no se versionan.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Callable, Iterable, Mapping

from . import congreso

RAIZ = Path(__file__).resolve().parent.parent
LARGO_MAX = 300
MAX_VOTACIONES = 4
POSICIONES = ("a_favor", "en_contra", "matizada", "sin_posicion")
TIPOS_FUENTE_POSICION = ("programa", "comunicado")
TIPOS_FUENTE_INICIATIVA = ("iniciativa", "diario_sesiones")
SENTIDOS_INICIATIVA = ("a_favor", "en_contra", "matizada")
ALCANCES = ("especifica", "amplia")
VOTOS = ("si", "no", "abstencion", "no_vota", "dividido")
MESES = "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split()


# ---------- Datos abiertos y votaciones por llamamiento ----------


def descargador(cache: Path | None = None) -> Callable[[str], dict]:
    """Función que descarga con `congreso.descargar` el JSON de una votación y, si se da `cache`, lo guarda."""

    def obtener(url: str) -> dict:
        fichero = cache / ("_".join(url.split("/")[-5:-1]) + ".json") if cache else None
        if fichero and fichero.exists():
            return json.loads(fichero.read_text(encoding="utf-8"))
        datos = congreso.descargar(url)
        if fichero:
            cache.mkdir(parents=True, exist_ok=True)
            fichero.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        return datos

    return obtener


def _norm_nombre(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z, ]", "", s).strip()


def contar_llamamiento(texto: str, referencia: Mapping, partidos: Iterable[str]) -> tuple[dict[str, str], dict[str, int], list[str]]:
    """Voto de cada partido en una votación por llamamiento, a partir del texto del Diario de Sesiones.

    `texto` es el tramo con las listas «Señoras y señores diputados que dijeron «sí»…» (y los votos
    telemáticos); `referencia`, el JSON de datos abiertos de una votación del mismo día, que da el grupo de
    cada diputado. Devuelve (voto de cada partido, totales contados, nombres sin identificar) para comparar
    los totales con el resultado oficial. Cada diputado cuenta una vez.
    """
    roster = {_norm_nombre(d["diputado"]): d for d in referencia.get("votaciones", [])}
    seccion, por, vistos, sin_casar = None, collections.defaultdict(list), set(), []
    totales: collections.Counter = collections.Counter()
    sentidos = {"sí": "Sí", "no": "No", "abstención": "Abstención"}
    for linea in texto.splitlines():
        cabecera = re.search(r"(?:dijeron|votaron) «([^»]+)»", linea)
        if cabecera:
            seccion = sentidos.get(cabecera.group(1).lower())  # una cabecera desconocida corta la lista
            continue
        if seccion is None:
            continue
        for celda in re.split(r"\s{2,}", linea.strip()):
            if not re.match(r"^[A-ZÁÉÍÓÚÑÜÀÈÒÇ][^,]+, [A-ZÁÉÍÓÚÑÜÀÈÒÇ]", celda):
                continue
            n = _norm_nombre(celda)
            candidatos = [n] if n in roster else [k for k in roster if k.startswith(n)]
            if len(candidatos) != 1:
                sin_casar.append(celda)
                continue
            d = roster[candidatos[0]]
            if d["diputado"] in vistos:
                continue
            vistos.add(d["diputado"])
            totales[seccion] += 1
            p = congreso.partido_de(d["diputado"], d.get("grupo", ""))
            if p:
                por[p].append(seccion)
    return {p: congreso.voto_partido(por.get(p, [])) for p in partidos}, dict(totales), sin_casar


# ---------- Programas ----------


def extraer_programa(pdf: Path) -> str:
    """Texto de un PDF con marcas `=====PAGINA n=====` por página (pdftotext -layout)."""
    texto = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True, check=True).stdout
    trozos = texto.split("\f")
    if trozos and not trozos[-1].strip():
        trozos = trozos[:-1]  # pdftotext termina cada página con un salto de página
    return "".join(f"=====PAGINA {i}=====\n{p}" for i, p in enumerate(trozos, start=1))


def paginas(texto: str) -> dict[int, str]:
    out = {}
    for trozo in texto.split("=====PAGINA ")[1:]:
        n, _, cuerpo = trozo.partition("=====")
        out[int(n)] = cuerpo
    return out


def _norm_texto(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"(\w)-\s+(\w)", r"\1\2", s)  # palabras partidas con guion a final de línea
    s = re.sub(r"[«»“”\"'’‘]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _en_orden(cita: str, texto: str, hueco: int = 2) -> bool:
    """Las palabras de la cita aparecen en orden en el texto, con como mucho `hueco` palabras intercaladas
    entre dos seguidas (rótulos o cabeceras que la extracción del PDF mete en mitad de una frase)."""
    c, t = cita.split(), texto.split()
    if not c:
        return False
    for inicio in (i for i, w in enumerate(t) if w == c[0]):
        j = inicio
        for w in c[1:]:
            k = next((k for k in range(j + 1, min(j + 2 + hueco, len(t))) if t[k] == w), None)
            if k is None:
                break
            j = k
        else:
            return True
    return False


def pagina_de_cita(pags: Mapping[int, str], pagina: int, cita: str) -> int | None:
    """Página en la que está la cita entera: la indicada o una contigua (también si sigue en la siguiente)."""
    c = _norm_texto(cita)
    candidatas = [n for n in (pagina, pagina - 1, pagina + 1) if n in pags]
    for n in candidatas:
        if c in _norm_texto(pags[n]):
            return n
    for n in candidatas:  # la cita empieza en una página y sigue en la siguiente
        if c in _norm_texto(pags[n] + " " + pags.get(n + 1, "")):
            return n
    for n in candidatas:  # con palabras sueltas intercaladas por la extracción
        if _en_orden(c, _norm_texto(pags[n] + " " + pags.get(n + 1, ""))):
            return n
    # Texto a dos columnas: cada frase de la cita, entera, en la página indicada.
    frases = [f.strip() for f in re.split(r"[.;:]", c) if len(f.strip()) > 25]
    if frases and all(f in _norm_texto(pags.get(pagina, "")) for f in frases):
        return pagina
    return None


# ---------- Posiciones y votaciones ----------


def fecha_larga(fecha: str) -> str:
    a, m, d = fecha.split("-")
    return f"{int(d)} de {MESES[int(m) - 1]} de {a}"


def posicion(partido: str, medida: str, prog: Mapping | None) -> dict:
    """Posición según el programa de un partido en una medida (`prog`: su fichero de programa)."""
    prog = prog or {}
    e = prog.get("medidas", {}).get(medida)
    docs = prog.get("documentos", [])
    if e is None or e.get("posicion") == "sin_posicion":
        return {
            "partido_id": partido,
            "posicion": "sin_posicion",
            "argumento": prog.get("argumento_sin_posicion"),
            "fecha": max(d["fecha"] for d in docs) if docs else None,
            "legislatura": (e or {}).get("legislatura") or prog.get("legislatura"),
            "fuentes": [{"tipo": "programa", "titulo": d["titulo"], "url": d["url"], "referencia": "Consultado; no menciona la medida"} for d in docs],
        }
    return {
        "partido_id": partido,
        "posicion": e["posicion"],
        "argumento": e["argumento"],
        "fecha": e.get("fecha"),
        "legislatura": e.get("legislatura") or prog.get("legislatura"),
        "fuentes": [{k: f[k] for k in ("tipo", "titulo", "url", "referencia")} for f in e["fuentes"]],
    }


def iniciativa(partido: str, e: Mapping | None) -> dict | None:
    """Iniciativa del partido sobre la medida (contrato `Iniciativa` de src/lib/schema.ts), si la tiene."""
    i = (e or {}).get("iniciativa")
    if not i:
        return None
    return {
        "partido_id": partido,
        "sentido": i["sentido"],
        "alcance": i["alcance"],
        "argumento": i["argumento"],
        "fecha": i["fecha"],
        "legislatura": i["legislatura"],
        "fuentes": [{k: f[k] for k in ("tipo", "titulo", "url", "referencia")} for f in i["fuentes"]],
    }


def fuentes_votacion(v: Mapping) -> list[dict]:
    """Ficha de la iniciativa, resultado oficial y Diario de Sesiones del debate (como en vivienda)."""
    fuentes = []
    if v.get("url_ficha"):
        fuentes.append({
            "tipo": "iniciativa",
            "titulo": f"Ficha de la iniciativa {v['expediente']} en la web del Congreso" if v.get("expediente") else "Ficha de la iniciativa en la web del Congreso",
            "url": v["url_ficha"],
            "referencia": "textos, tramitación, diarios de sesiones y votaciones",
        })
    if v.get("url_pdf") and not v.get("votos_llamamiento"):
        fuentes.append({
            "tipo": "votacion",
            "titulo": f"Resultado de la votación del Pleno del {fecha_larga(v['fecha'])} (Congreso de los Diputados)",
            "url": v["url_pdf"],
            "referencia": f"Sesión plenaria n.º {v['sesion']}, votación n.º {v['numero']}",
        })
    if v.get("diario_sesiones"):
        ds = v["diario_sesiones"]
        n = re.search(r"DSCD-\d+-PL-(\d+)", ds["url"])
        fuentes.append({
            "tipo": "diario_sesiones",
            "titulo": "Diario de Sesiones del Congreso de los Diputados, Pleno" + (f", n.º {n.group(1)}" if n else ""),
            "url": ds["url"],
            "referencia": ds["referencia"],
        })
    return fuentes


def votacion(v: Mapping, votos: Mapping[str, str]) -> dict:
    """Votación en el formato de `posiciones.json` (contrato `Votacion` de src/lib/schema.ts)."""
    out = {
        "id": v["id"],
        "titulo": v["titulo"],
        "descripcion": v["descripcion"],
        "sentido": v["sentido"],
        "alcance": v.get("alcance", "especifica"),
        "fecha": v["fecha"],
        "legislatura": v["legislatura"],
        "resultado": v["resultado"],
        "fuentes": fuentes_votacion(v),
    }
    if v.get("url_json") and not v.get("votos_llamamiento"):
        out["url_datos"] = v["url_json"]
    out["votos"] = dict(votos)
    return out


# ---------- Ensamblado ----------


def _leer(f: Path) -> dict:
    return json.loads(f.read_text(encoding="utf-8"))


def _comprobar_cita(e: Mapping, dir_programas: Path, textos: dict, ruta: str, avisos: list[str]) -> None:
    if e.get("fichero_txt") is None:
        return  # cita de una iniciativa o de un comunicado: no hay texto local
    if not (e.get("cita_textual") and e.get("pagina")):
        avisos.append(f"{ruta}: sin cita_textual o página para comprobar")
        return
    if e["fichero_txt"] not in textos:
        f = dir_programas / e["fichero_txt"]
        textos[e["fichero_txt"]] = paginas(f.read_text(encoding="utf-8")) if f.exists() else None
    pags = textos[e["fichero_txt"]]
    if pags is None:
        avisos.append(f"{ruta}: no está el texto {e['fichero_txt']} en --programas")
        return
    n = pagina_de_cita(pags, int(e["pagina"]), e["cita_textual"])
    if n is None:
        avisos.append(f"{ruta}: la cita no está en {e['fichero_txt']} p. {e['pagina']}")
    elif n != int(e["pagina"]):
        avisos.append(f"{ruta}: la cita está en la p. {n}, no en la {e['pagina']}")


def ensamblar(
    dir_tema: Path,
    *,
    obtener_json: Callable[[str], dict],
    dir_programas: Path | None = None,
    partidos: list[str] | None = None,
) -> tuple[dict, list[str]]:
    """Devuelve (contenido de posiciones.json, avisos) para el tema de `dir_tema`."""
    config = _leer(dir_tema / "config.json")
    partidos = partidos or congreso.partidos_globales()
    base = dir_tema / "posiciones"
    avisos: list[str] = []

    programas = {}
    for p in partidos:
        f = base / "programa" / f"{p}.json"
        if not f.exists():
            avisos.append(f"programa/{p}.json: no existe")
            continue
        programas[p] = _leer(f)
        if not programas[p].get("argumento_sin_posicion"):
            avisos.append(f"programa/{p}.json: falta argumento_sin_posicion")
        if not programas[p].get("documentos"):
            avisos.append(f"programa/{p}.json: sin documentos consultados")

    textos: dict = {}
    medidas = []
    for m in config["medidas"]:
        if "ref" in m:  # medida de otro tema: sus posiciones están en su posiciones.json
            continue
        mid = m["id"]
        posiciones, iniciativas = [], []
        for p in partidos:
            e = programas.get(p, {}).get("medidas", {}).get(mid)
            if p in programas and e is None:
                avisos.append(f"{mid}/{p}: falta la medida en programa/{p}.json")
            if e and e.get("posicion") != "sin_posicion" and dir_programas:
                _comprobar_cita(e, dir_programas, textos, f"{mid}/{p}", avisos)
            pos = posicion(p, mid, programas.get(p))
            if pos["posicion"] not in POSICIONES:
                avisos.append(f"{mid}/{p}: posición {pos['posicion']!r} no admitida")
            if len(pos["argumento"] or "") > LARGO_MAX:
                avisos.append(f"{mid}/{p}: argumento de {len(pos['argumento'])} caracteres")
            if not pos["legislatura"]:
                avisos.append(f"{mid}/{p}: sin legislatura")
            for fu in pos["fuentes"]:
                if fu["tipo"] not in TIPOS_FUENTE_POSICION:
                    avisos.append(f"{mid}/{p}: fuente de tipo {fu['tipo']!r} en la posición según el programa (las iniciativas van en `iniciativa`)")
            posiciones.append(pos)
            ini = iniciativa(p, e)
            if ini:
                ruta = f"{mid}/{p}/iniciativa"
                if ini["sentido"] not in SENTIDOS_INICIATIVA:
                    avisos.append(f"{ruta}: sentido {ini['sentido']!r} no admitido")
                if ini["alcance"] not in ALCANCES:
                    avisos.append(f"{ruta}: alcance {ini['alcance']!r} no admitido")
                if ini["sentido"] == "en_contra" and ini["alcance"] != "especifica":
                    avisos.append(f"{ruta}: una iniciativa en contra debe proponer expresamente suprimir o rechazar la medida (alcance especifica)")
                if len(ini["argumento"] or "") > LARGO_MAX:
                    avisos.append(f"{ruta}: argumento de {len(ini['argumento'])} caracteres")
                if not ini["fuentes"] or any(fu["tipo"] not in TIPOS_FUENTE_INICIATIVA for fu in ini["fuentes"]):
                    avisos.append(f"{ruta}: sin fuentes o con fuentes que no son del BOCG o del Diario de Sesiones")
                iniciativas.append(ini)

        f = base / "votaciones" / f"{mid}.json"
        if not f.exists():
            avisos.append(f"votaciones/{mid}.json: no existe")
        lista = _leer(f).get("votaciones", []) if f.exists() else []
        for alcance in ALCANCES:
            n = sum(v.get("alcance", "especifica") == alcance for v in lista)
            if n > MAX_VOTACIONES:
                avisos.append(f"{mid}: {n} votaciones de alcance {alcance}; el máximo es {MAX_VOTACIONES}")
        if [v["fecha"] for v in lista] != sorted((v["fecha"] for v in lista), reverse=True):
            avisos.append(f"{mid}: las votaciones no van de la más reciente a la más antigua")
        votaciones = []
        for v in lista:
            ruta = f"{mid}/{v['id']}"
            if v.get("sentido") not in ("a_favor", "en_contra"):
                avisos.append(f"{ruta}: sentido {v.get('sentido')!r} no admitido")
            if v.get("alcance", "especifica") not in ALCANCES:
                avisos.append(f"{ruta}: alcance {v.get('alcance')!r} no admitido")
            if len(v.get("descripcion", "")) > LARGO_MAX:
                avisos.append(f"{ruta}: descripción de {len(v['descripcion'])} caracteres")
            if not v.get("diario_sesiones"):
                avisos.append(f"{ruta}: sin página del Diario de Sesiones")
            if v.get("votos_llamamiento"):
                votos = v["votos_llamamiento"]
                if set(votos) != set(partidos) or any(x not in VOTOS for x in votos.values()):
                    avisos.append(f"{ruta}: votos_llamamiento incompleto o con valores no admitidos")
            else:
                datos = obtener_json(v["url_json"])
                votos = congreso.votos_por_partido(datos, partidos)
                presentes = {congreso.partido_de(d.get("diputado", ""), d.get("grupo", "")) for d in datos.get("votaciones", [])}
                for p in sorted(set(partidos) & set(congreso.GRUPOS.values()) - presentes):
                    # Un partido con grupo propio siempre tiene diputados en la votación; si no, ha cambiado el código del grupo.
                    avisos.append(f"{ruta}: ningún diputado de {p} en los datos abiertos (¿cambió el código del grupo?)")
                if congreso.resultado(datos) != v["resultado"]:
                    avisos.append(f"{ruta}: resultado {v['resultado']!r} y datos abiertos {congreso.resultado(datos)!r}")
            votaciones.append(votacion(v, votos))
        if len({v["id"] for v in votaciones}) != len(votaciones):
            avisos.append(f"{mid}: ids de votaciones duplicados")
        medidas.append({"medida_id": mid, "posiciones": posiciones, "iniciativas": iniciativas, "votaciones": votaciones})
    return {"tema": config["slug"], "medidas": medidas}, avisos


ABREV = {"a_favor": "F", "en_contra": "C", "matizada": "M", "sin_posicion": "·"}


def tabla(salida: Mapping) -> str:
    """Posición según el programa por medida y partido (F, C, M, ·), con la de su iniciativa tras una barra
    si la tiene (p. ej. `·/F`), y número de votaciones."""
    if not salida["medidas"]:
        return ""
    filas = ["medida".ljust(36) + " ".join(p["partido_id"][:5].ljust(5) for p in salida["medidas"][0]["posiciones"]) + "  votaciones"]
    for m in salida["medidas"]:
        ini = {i["partido_id"]: i["sentido"] for i in m.get("iniciativas", [])}
        celdas = " ".join(
            (ABREV.get(p["posicion"], "?") + (f"/{ABREV.get(ini[p['partido_id']], '?')}" if p["partido_id"] in ini else "")).ljust(5)
            for p in m["posiciones"]
        )
        filas.append(m["medida_id"][:35].ljust(36) + celdas + f"  {len(m['votaciones'])}")
    return "\n".join(filas)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m lib.posiciones", description="Ensambla posiciones.json desde temas/<slug>/posiciones/.")
    sub = ap.add_subparsers(dest="orden", required=True)
    a = sub.add_parser("ensamblar")
    a.add_argument("slug")
    a.add_argument("--escribir", action="store_true")
    a.add_argument("--programas", type=Path)
    a.add_argument("--cache", type=Path)
    e = sub.add_parser("extraer-programa")
    e.add_argument("pdf", type=Path)
    e.add_argument("salida", type=Path)
    ll = sub.add_parser("llamamiento")
    for nombre in ("pdf", "pag_ini", "pag_fin", "referencia", "inicio", "fin"):
        ll.add_argument(nombre)
    args = ap.parse_args(argv)

    if args.orden == "extraer-programa":
        args.salida.write_text(extraer_programa(args.pdf), encoding="utf-8")
        return 0
    if args.orden == "llamamiento":
        texto = subprocess.run(["pdftotext", "-layout", "-f", args.pag_ini, "-l", args.pag_fin, args.pdf, "-"], capture_output=True, text=True, check=True).stdout
        ini = texto.index(args.inicio)
        tramo = texto[ini : texto.index(args.fin, ini)]
        referencia = json.loads(Path(args.referencia).read_text(encoding="utf-8-sig"))
        votos, totales, sin_casar = contar_llamamiento(tramo, referencia, congreso.partidos_globales())
        print(json.dumps({"votos_llamamiento": votos, "totales_contados": totales, "sin_identificar": sin_casar}, ensure_ascii=False, indent=2))
        return 0
    dir_tema = RAIZ / "temas" / args.slug
    salida, avisos = ensamblar(dir_tema, obtener_json=descargador(args.cache), dir_programas=args.programas)
    print(tabla(salida))
    if not args.programas:
        print("(sin --programas: no se comprueban las citas de los programas)")
    print(f"\n{len(avisos)} avisos")
    for x in avisos:
        print("AVISO", x)
    if args.escribir:
        (dir_tema / "posiciones.json").write_text(json.dumps(salida, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"escrito temas/{args.slug}/posiciones.json")
    return 1 if avisos else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
