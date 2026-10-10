"""Comunidades y ciudades autónomas: claves de las series `por_ccaa` (ISO 3166-2:ES) y nombres cortos."""

# Nombres cortos para rotular las gráficas y redactar las notas. Las claves deben coincidir con
# CODIGOS_CCAA de src/lib/schema.ts (lo comprueba tests/test_writer.py) y los nombres con NOMBRES_CCAA
# de src/lib/estilos-series.ts (lo comprueba estilos-series.test.ts).
NOMBRES_CCAA = {
    "ES-AN": "Andalucía", "ES-AR": "Aragón", "ES-AS": "Asturias", "ES-CB": "Cantabria", "ES-CE": "Ceuta",
    "ES-CL": "Castilla y León", "ES-CM": "Castilla-La Mancha", "ES-CN": "Canarias", "ES-CT": "Cataluña",
    "ES-EX": "Extremadura", "ES-GA": "Galicia", "ES-IB": "Baleares", "ES-MC": "Murcia", "ES-MD": "Madrid",
    "ES-ML": "Melilla", "ES-NC": "Navarra", "ES-PV": "País Vasco", "ES-RI": "La Rioja", "ES-VC": "C. Valenciana",
}
CODIGOS_CCAA = list(NOMBRES_CCAA)
