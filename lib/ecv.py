"""Microdatos de la Encuesta de Condiciones de Vida (ECV) del INE y la sobrecarga del coste de la vivienda.

Ficheros de usuario transversales, base 2013 (2008 en adelante; el de 2008 viene en 7z):
https://www.ine.es/ftp/microdatos/ecv/ecv_b2013/datos_<año>.zip. Mecanismo verificado el 2026-10-20. Cada zip
trae, a veces dentro de otro zip, los ficheros de Eurostat (EU-SILC) en CSV: `esudb<aa>d.csv` (hogar: región,
`DB040`), `esudb<aa>h.csv` (hogar: tenencia, costes, renta) y el de personas (`esudb<aa>r.csv`,
`esudb<aa>r_AROPE.csv` o `ECV_Tr_<año>.csv` según el año: peso `RB050`, residencia `RB200`). Los microdatos no
se guardan en el repositorio: se descargan al ejecutar el notebook (unos 500 MB entre todos los años).

- `get(anio)`: los tres ficheros de un año, con las columnas que usa `sobrecarga`.
- `sobrecarga(ficheros, tenencia)`: tasa de sobrecarga del coste de la vivienda con la fórmula de Eurostat
  (EU-SILC methodology – housing conditions, punto 5), para España y cada comunidad (NUTS 2), con el tamaño de
  la muestra (hogares y personas).
- `propiedad_por_edad(ficheros, edad_min, edad_max)`: % de hogares en propiedad (con o sin hipoteca) cuya persona
  de referencia tiene esa edad, como la tabla 9994 del INE (que reproduce), para España y cada comunidad.

Ejemplo real::

    from lib import ecv

    tasas = ecv.sobrecarga(ecv.get(2024)[0], "alquiler_mercado")
"""

from __future__ import annotations

import io
import re
import tempfile
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd
import py7zr
import requests

from ._http import pedir
from .tipos import FuenteMeta

ORGANISMO = "INE"
URL_ZIP = "https://www.ine.es/ftp/microdatos/ecv/ecv_b2013/datos_{anio}.zip"
URL_MICRODATOS = (
    "https://www.ine.es/dyngs/INEbase/es/operacion.htm?c=Estadistica_C&cid=1254736176807"
    "&menu=resultados&secc=1254736195153&idp=1254735976608"
)
CABECERA = {"User-Agent": "Mozilla/5.0 (compatible; EspanaenDatos)"}
PRIMER_ANIO = 2008

# Regiones NUTS 2 de la ECV (`DB040`) → códigos ISO 3166-2:ES de `comunidades` en global.json
NUTS_A_CCAA = {
    "ES11": "ES-GA", "ES12": "ES-AS", "ES13": "ES-CB", "ES21": "ES-PV", "ES22": "ES-NC", "ES23": "ES-RI",
    "ES24": "ES-AR", "ES30": "ES-MD", "ES41": "ES-CL", "ES42": "ES-CM", "ES43": "ES-EX", "ES51": "ES-CT",
    "ES52": "ES-VC", "ES53": "ES-IB", "ES61": "ES-AN", "ES62": "ES-MC", "ES63": "ES-CE", "ES64": "ES-ML",
    "ES70": "ES-CN",
}
# Tenencia: `HH021` desde 2012; `HH020` (otra codificación) en los ficheros anteriores
CODIGOS_TENENCIA = {
    "HH021": {1: "propiedad", 2: "propiedad", 3: "alquiler_mercado", 4: "alquiler_reducido", 5: "cesion"},
    "HH020": {1: "propiedad", 2: "alquiler_mercado", 3: "alquiler_reducido", 4: "cesion"},
}
TENENCIAS = {
    "alquiler_mercado": {"alquiler_mercado"},
    "total": {"propiedad", "alquiler_mercado", "alquiler_reducido", "cesion"},
}
COLUMNAS = {
    "d": ["DB010", "DB030", "DB040", "DB090"],
    "h": ["HB030", "HB080", "HH020", "HH021", "HH070", "HY020", "HY070G"],
    "r": ["RB030", "RB050", "RB080", "RB200"],
}
UMBRAL_SOBRECARGA = 40  # % de la renta disponible (Eurostat)
_FICHERO = re.compile(r"(?:esudb\d\d([dhr])(?:_arope)?|ecv_t([dhr])_\d{4})\.(?:csv|tab)$", re.I)


class EcvError(RuntimeError):
    """Error de descarga o fichero de microdatos con un formato no reconocido."""


def _buscar(zf: zipfile.ZipFile, encontrados: dict[str, bytes]) -> None:
    """Recorre el zip (y los zip que contiene) y guarda el primer fichero d, h y r de Eurostat."""
    for nombre in zf.namelist():
        m = _FICHERO.search(nombre)
        if m:
            tipo = (m.group(1) or m.group(2)).lower()
            # Si hay dos (p. ej. esudb24r.csv y ECV_Tr_2024.tab), vale el de Eurostat
            if tipo not in encontrados or nombre.lower().split("/")[-1].startswith("esudb"):
                encontrados[tipo] = zf.read(nombre)
        elif nombre.lower().endswith(".zip"):
            _buscar(zipfile.ZipFile(io.BytesIO(zf.read(nombre))), encontrados)
        elif nombre.lower().endswith(".7z"):
            _buscar_7z(zf.read(nombre), encontrados)


def _buscar_7z(contenido: bytes, encontrados: dict[str, bytes]) -> None:
    """Como `_buscar`, en un 7z (el formato del fichero de 2008)."""
    with tempfile.TemporaryDirectory() as tmp, py7zr.SevenZipFile(io.BytesIO(contenido)) as z:
        z.extractall(tmp)
        for f in sorted(Path(tmp).rglob("*")):
            m = _FICHERO.search(f.name)
            if m and f.is_file():
                encontrados.setdefault((m.group(1) or m.group(2)).lower(), f.read_bytes())


def _leer_csv(contenido: bytes, columnas: list[str]) -> pd.DataFrame:
    texto = contenido.decode("latin-1")
    cabecera = texto.split("\n", 1)[0]
    sep = "\t" if "\t" in cabecera else ";" if ";" in cabecera else ","
    df = pd.read_csv(io.StringIO(texto), sep=sep, dtype=str, usecols=lambda c: c.strip('"') in columnas)
    df.columns = [c.strip('"') for c in df.columns]
    for c in df.columns:
        if c != "DB040":
            df[c] = pd.to_numeric(df[c].str.strip().replace("", None), errors="coerce")
        else:
            df[c] = df[c].str.strip()
    return df


def leer_zip(contenido: bytes, anio: int) -> dict[str, pd.DataFrame]:
    """Ficheros `d`, `h` y `r` de un zip de microdatos, con las columnas de `COLUMNAS` que existan ese año."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(contenido))
    except zipfile.BadZipFile as e:
        raise EcvError(f"{anio}: no es un zip") from e
    encontrados: dict[str, bytes] = {}
    _buscar(zf, encontrados)
    faltan = set(COLUMNAS) - set(encontrados)
    if faltan:
        raise EcvError(f"{anio}: no se encuentran los ficheros {', '.join(sorted(faltan))} de Eurostat")
    out = {t: _leer_csv(encontrados[t], cols) for t, cols in COLUMNAS.items()}
    for t, df in out.items():
        obligatorias = [c for c in COLUMNAS[t] if c not in ("HH020", "HH021")]
        falta = [c for c in obligatorias if c not in df.columns]
        if falta or not {"HH020", "HH021"} & set(out["h"].columns):
            raise EcvError(f"{anio}: faltan columnas en {t}: {falta or ['HH020/HH021']}")
    return out


def get(
    anio: int,
    *,
    fecha_consulta: str | None = None,
    sesion: requests.Session | None = None,
    reintentos: int = 2,
) -> tuple[dict[str, pd.DataFrame], FuenteMeta]:
    """Descarga los microdatos de un año. Devuelve `(ficheros d/h/r, fuente)`; la `serie` de la fuente es "espana"."""
    if anio < PRIMER_ANIO:
        raise ValueError(f"los microdatos de {anio} no se leen (el primer año es {PRIMER_ANIO})")
    url = URL_ZIP.format(anio=anio)
    r = pedir(
        sesion or requests.Session(), url, None,
        error_cls=EcvError, etiqueta=str(anio), mensaje=lambda r: r.text[:200], headers=CABECERA,
        reintentos=reintentos,
    )
    fuente = FuenteMeta(
        "espana", ORGANISMO, f"Encuesta de Condiciones de Vida, microdatos {anio} (base 2013)", url,
        fecha_consulta or date.today().isoformat(),
    )
    return leer_zip(r.content, anio), fuente


def _hogares(ficheros: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Hogares con su comunidad (`ccaa`) y su tenencia (`tenencia`, de `CODIGOS_TENENCIA`)."""
    h, d = ficheros["h"], ficheros["d"]
    variable = "HH021" if "HH021" in h.columns and h["HH021"].notna().any() else "HH020"
    hog = h.merge(d, left_on="HB030", right_on="DB030")
    return hog.assign(ccaa=hog["DB040"].map(NUTS_A_CCAA), tenencia=hog[variable].map(CODIGOS_TENENCIA[variable]))


def _por_ccaa(filas: pd.DataFrame, resumen) -> pd.DataFrame:
    """`resumen` de España ("espana") y de cada comunidad, con el índice `serie`."""
    out = pd.concat([resumen(filas).to_frame("espana").T, filas.groupby("ccaa").apply(resumen, include_groups=False)])
    out[["hogares"]] = out[["hogares"]].astype(int)
    out.index.name = "serie"
    return out


def sobrecarga(ficheros: dict[str, pd.DataFrame], tenencia: str = "total") -> pd.DataFrame:
    """Tasa de sobrecarga del coste de la vivienda (%) de las personas de los hogares con esa `tenencia`.

    Fórmula de Eurostat: carga = (HH070 × 12 − HY070G) / (HY020 − HY070G) × 100, con carga 0 si el coste neto es
    ≤ 0 y 100 si la renta neta es ≤ 0 o menor que el coste; sobrecarga si la carga supera el 40 %. Se cuenta por
    personas que residen en el hogar (`RB200` = 1), ponderadas con `RB050`, de los hogares con renta conocida.
    Devuelve una fila por comunidad (código ISO) y otra para "espana": `tasa`, `hogares` y `personas` de la muestra.
    """
    if tenencia not in TENENCIAS:
        raise ValueError(f"tenencia {tenencia!r} no válida; usa {', '.join(TENENCIAS)}")
    hog = _hogares(ficheros)
    hog = hog[hog["HY020"].notna() & hog["HH070"].notna() & hog["tenencia"].isin(TENENCIAS[tenencia])]
    ayudas = hog["HY070G"].fillna(0)
    coste = hog["HH070"] * 12 - ayudas
    renta = hog["HY020"] - ayudas
    carga = (coste / renta * 100).mask(coste <= 0, 0).mask((renta <= 0) | (renta < coste), 100)
    hog = hog.assign(sobrecarga=carga > UMBRAL_SOBRECARGA)
    r = ficheros["r"]
    personas = r[r["RB200"] == 1].assign(HB030=lambda x: x["RB030"] // 100).merge(hog, on="HB030")

    def resumen(g: pd.DataFrame) -> pd.Series:
        return pd.Series({
            "tasa": (g["RB050"] * g["sobrecarga"]).sum() / g["RB050"].sum() * 100,
            "hogares": g["HB030"].nunique(),
            "personas": len(g),
        })

    out = _por_ccaa(personas, resumen)
    out["personas"] = out["personas"].astype(int)
    return out


def propiedad_por_edad(ficheros: dict[str, pd.DataFrame], edad_min: int, edad_max: int) -> pd.DataFrame:
    """% de hogares en propiedad (con o sin hipoteca) cuya persona de referencia tiene entre `edad_min` y `edad_max` años.

    Como la tabla 9994 del INE: la persona de referencia es la primera responsable de la vivienda (`HB080`); su edad,
    la que cumple en el año anterior a la encuesta, el de referencia de la renta (año − 1 − `RB080`). Hogares
    ponderados con `DB090`. Devuelve una fila por comunidad y otra para "espana": `tasa` y `hogares` de la muestra.
    """
    hog = _hogares(ficheros)
    anio = int(ficheros["d"]["DB010"].iloc[0])
    nacimiento = ficheros["r"].set_index("RB030")["RB080"]
    edad = anio - 1 - hog["HB080"].map(nacimiento)
    hog = hog[edad.between(edad_min, edad_max) & hog["tenencia"].notna()]

    def resumen(g: pd.DataFrame) -> pd.Series:
        propiedad = g["tenencia"] == "propiedad"
        return pd.Series({"tasa": (g["DB090"] * propiedad).sum() / g["DB090"].sum() * 100, "hogares": len(g)})

    return _por_ccaa(hog, resumen)
