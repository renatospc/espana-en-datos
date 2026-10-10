"""Comunidades y ciudades autónomas: claves de las series `por_ccaa` (ISO 3166-2:ES) y nombres cortos.

Se leen de `comunidades` en `global.json`, la lista única que también usa la web (src/lib/schema.ts
y src/lib/estilos-series.ts).
"""

import json
from pathlib import Path

GLOBAL = Path(__file__).resolve().parent.parent / "global.json"

# Nombres cortos para rotular las gráficas y redactar las notas, en el orden de global.json.
NOMBRES_CCAA = {
    c["codigo"]: c["nombre"] for c in json.loads(GLOBAL.read_text(encoding="utf-8"))["comunidades"]
}
CODIGOS_CCAA = list(NOMBRES_CCAA)
