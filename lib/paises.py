"""Países de las gráficas `dispersion` (METODOLOGIA §2.6): códigos ISO 3166-1 alfa-3, nombres y grupos.

Se leen de `paises` en `global.json`, la lista única que también usa la web (src/lib/schema.ts y
`nombrePunto` de src/lib/estilos-series.ts). Las medias (UE-27, OCDE) son puntos solo si la fuente
las publica para los dos ejes: se identifican por el `codigo_iso` de su benchmark.
"""

import json
from pathlib import Path

GLOBAL = Path(__file__).resolve().parent.parent / "global.json"

_GLOBAL = json.loads(GLOBAL.read_text(encoding="utf-8"))

# Nombre corto de cada país, en el orden de global.json.
NOMBRES_PAISES = {p["codigo"]: p["nombre"] for p in _GLOBAL["paises"]}
# Grupos (universos) de cada país: "ocde", "ue27".
GRUPOS_PAISES = {p["codigo"]: list(p["grupos"]) for p in _GLOBAL["paises"]}
# Agregados que pueden ser un punto más: `codigo_iso` de los benchmarks que no son países (EU27_2020, OECD).
NOMBRES_AGREGADOS = {
    b["codigo_iso"]: b["nombre"]
    for b in _GLOBAL["benchmarks"]
    if b.get("codigo_iso") and b["codigo_iso"] not in NOMBRES_PAISES
}
UNIVERSOS = sorted({g for gs in GRUPOS_PAISES.values() for g in gs})

# Códigos de Eurostat (ISO alfa-2 salvo Grecia, EL) de los países de global.json.
_ALFA2 = {
    "AUS": "AU", "AUT": "AT", "BEL": "BE", "BGR": "BG", "CAN": "CA", "CHE": "CH", "CHL": "CL",
    "COL": "CO", "CRI": "CR", "CYP": "CY", "CZE": "CZ", "DEU": "DE", "DNK": "DK", "ESP": "ES",
    "EST": "EE", "FIN": "FI", "FRA": "FR", "GBR": "UK", "GRC": "EL", "HRV": "HR", "HUN": "HU",
    "IRL": "IE", "ISL": "IS", "ISR": "IL", "ITA": "IT", "JPN": "JP", "KOR": "KR", "LTU": "LT",
    "LUX": "LU", "LVA": "LV", "MEX": "MX", "MLT": "MT", "NLD": "NL", "NOR": "NO", "NZL": "NZ",
    "POL": "PL", "PRT": "PT", "ROU": "RO", "SVK": "SK", "SVN": "SI", "SWE": "SE", "TUR": "TR",
    "USA": "US",
}
CODIGOS_EUROSTAT = {c: _ALFA2[c] for c in NOMBRES_PAISES}


def paises_de(universo: str) -> list[str]:
    """Códigos de los países de un universo, en el orden de global.json."""
    if universo not in UNIVERSOS:
        raise ValueError(f"universo desconocido: {universo!r}; válidos: {', '.join(UNIVERSOS)}")
    return [c for c, gs in GRUPOS_PAISES.items() if universo in gs]


def nombre_punto(codigo: str) -> str:
    """Nombre de un punto, como `nombrePunto` de la web: país, agregado o el propio código."""
    return NOMBRES_PAISES.get(codigo) or NOMBRES_AGREGADOS.get(codigo) or codigo
