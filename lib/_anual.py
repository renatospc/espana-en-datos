"""Agregación a periodos anuales para fuentes con series mensuales o trimestrales (INE, BdE)."""

from __future__ import annotations

import pandas as pd

from .tipos import COLUMNAS, validar_df

AGREGACIONES = ("media", "suma", "ultimo")


def agregar_anual(obs: pd.DataFrame, agregacion: str | None, etiqueta: str = "") -> pd.DataFrame:
    """Convierte observaciones `serie, anio, orden, valor` en el DataFrame estándar anual.

    - `agregacion=None`: la serie ya es anual; más de una observación por año es un error.
    - `media`/`suma`/`ultimo`: agrega los años **completos**. Un año con menos observaciones
      que el máximo de la serie (p. ej. el año en curso) se descarta, para no publicar medias
      o sumas parciales. `orden` fija la última observación del año.
    - Las observaciones sin valor (`NaN`) se ignoran.
    """
    if agregacion is not None and agregacion not in AGREGACIONES:
        raise ValueError(f"agregacion {agregacion!r} no válida; usa None o {', '.join(AGREGACIONES)}")
    obs = obs.dropna(subset=["valor"])
    filas = []
    for serie, g in obs.groupby("serie"):
        cuentas = g.groupby("anio").size()
        if agregacion is None:
            if (cuentas > 1).any():
                raise ValueError(
                    f"{etiqueta}{serie}: hay varias observaciones por año; "
                    f"indica agregacion ({', '.join(AGREGACIONES)})"
                )
            completos = cuentas.index
        else:
            completos = cuentas[cuentas == cuentas.max()].index
        for anio, ga in g[g["anio"].isin(completos)].groupby("anio"):
            ga = ga.sort_values("orden")
            v = {"media": ga["valor"].mean, "suma": ga["valor"].sum}.get(
                agregacion or "ultimo", lambda: ga["valor"].iloc[-1]
            )()
            filas.append((serie, int(anio), float(v)))
    return validar_df(pd.DataFrame(filas, columns=COLUMNAS))
