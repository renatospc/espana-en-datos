"""Formato común de los fetchers: metadatos de fuente y DataFrame estándar."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date

import pandas as pd

COLUMNAS = ["serie", "periodo", "valor"]

_URL = re.compile(r"^https?://\S+$")


@dataclass(frozen=True)
class FuenteMeta:
    """Fuente de una serie (METODOLOGIA §3.1). `serie` es la clave en `series`."""

    serie: str
    organismo: str
    dataset_codigo: str
    url: str
    fecha_consulta: str  # ISO 8601 (YYYY-MM-DD)

    def __post_init__(self) -> None:
        if not _URL.match(self.url):
            raise ValueError(f"fuente {self.serie!r}: url no válida: {self.url!r}")
        try:
            date.fromisoformat(self.fecha_consulta)
        except ValueError as e:
            raise ValueError(
                f"fuente {self.serie!r}: fecha_consulta no es ISO 8601: {self.fecha_consulta!r}"
            ) from e

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def validar_df(df: pd.DataFrame) -> pd.DataFrame:
    """Valida el DataFrame estándar `serie, periodo, valor` y lo devuelve normalizado.

    - `serie`: str; `periodo`: año entero; `valor`: float (NaN = sin dato).
    - Sin pares (serie, periodo) duplicados. Orden: serie, periodo.
    """
    if list(df.columns) != COLUMNAS:
        raise ValueError(f"columnas {list(df.columns)}; se esperaban {COLUMNAS}")
    out = df.copy()
    if not out["serie"].map(lambda x: isinstance(x, str) and x != "").all():
        raise ValueError("`serie` debe contener cadenas no vacías")
    try:
        periodo = pd.to_numeric(out["periodo"], errors="raise")
    except (ValueError, TypeError) as e:
        raise ValueError("`periodo` debe ser un año entero") from e
    if periodo.isna().any() or (periodo % 1 != 0).any():
        raise ValueError("`periodo` debe ser un año entero")
    out["periodo"] = periodo.astype("int64")
    try:
        out["valor"] = pd.to_numeric(out["valor"], errors="raise").astype("float64")
    except (ValueError, TypeError) as e:
        raise ValueError(
            "`valor` debe ser numérico (usa NaN/None para dato no disponible, nunca 'N/A')"
        ) from e
    dup = out.duplicated(["serie", "periodo"], keep=False)
    if dup.any():
        ejemplos = out.loc[dup, ["serie", "periodo"]].drop_duplicates().head(3).values.tolist()
        raise ValueError(f"pares (serie, periodo) duplicados, p. ej. {ejemplos}")
    return out.sort_values(["serie", "periodo"]).reset_index(drop=True)
