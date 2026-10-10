# {{NOMBRE_PLATAFORMA}}: notebooks y datos

Notebooks de Jupyter que generan los datos de las gráficas de **{{NOMBRE_PLATAFORMA}}** ([https://{{DOMINIO}}](https://{{DOMINIO}})), una plataforma cívica de datos socioeconómicos sobre España comparados con referencias internacionales. Cada notebook descarga las series de fuentes oficiales, las transforma con código visible y escribe el fichero de datos que usa la web.

Este repositorio se sincroniza automáticamente desde el proyecto y solo contiene los temas publicados en la web, que han pasado revisión humana. Cualquier cambio hecho aquí directamente se sobrescribe en la siguiente sincronización.

## Contenido

```text
temas/<tema>/notebooks/<id>.ipynb   Un notebook por gráfica, con sus salidas (los gráficos se ven en GitHub)
temas/<tema>/data/<id>.json         Datos de la gráfica generados por el notebook: series, fuentes y notas
temas/<tema>/data/<id>.csv          Los mismos datos en CSV
lib/                                Descarga de las fuentes oficiales y escritura de los datos
global.json                         Partidos, referencias internacionales y estilos de las gráficas
schemas/grafica-data.schema.json    Esquema con el que se valida cada data/<id>.json
pyproject.toml, uv.lock             Entorno de Python con versiones fijadas
LICENSE, LICENSE-DATA               Licencias (ver más abajo)
```

## Cómo ejecutar los notebooks

Necesitas [uv](https://docs.astral.sh/uv/getting-started/installation/), que instala Python 3.12 y las versiones exactas de `uv.lock`:

```bash
git clone https://github.com/renatospc/espana-en-datos.git
cd espana-en-datos
uv sync
```

Abre los notebooks desde su carpeta, `temas/<tema>/notebooks/`: buscan `global.json` y `lib/` subiendo desde el directorio de trabajo.

```bash
cd temas/<tema>/notebooks
uv run jupyter lab
```

Para ejecutar un notebook sin abrirlo, desde la misma carpeta:

```bash
uv run jupyter execute --inplace <id>.ipynb
```

Al ejecutarse, cada notebook descarga los datos de las fuentes oficiales (necesita conexión a internet) y reescribe `temas/<tema>/data/<id>.json`. El resultado puede diferir del publicado si el organismo ha revisado o ampliado la serie; la fecha de consulta de cada fuente figura en el JSON.

## Licencias y cómo atribuir

- **Datos, gráficos y textos** (`data/`, salidas y celdas de texto de los notebooks): [Creative Commons Atribución 4.0 Internacional (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/deed.es). Texto legal en [`LICENSE-DATA`](LICENSE-DATA).
- **Código** (celdas de código de los notebooks y `lib/`): MIT. Texto en [`LICENSE`](LICENSE).

Con CC BY 4.0 puedes copiar, adaptar y publicar el material, también con fines comerciales, siempre que cites la autoría, enlaces a la licencia e indiques si has hecho cambios. Por ejemplo:

> Fuente: {{NOMBRE_PLATAFORMA}} (https://{{DOMINIO}}), a partir de datos de Eurostat. Licencia CC BY 4.0.

Las series proceden de organismos oficiales con sus propias condiciones de reutilización: cita también el organismo original, que figura en `fuentes` de cada `data/<id>.json`. Guía de atribución completa para medios: [https://{{DOMINIO}}/prensa](https://{{DOMINIO}}/prensa).

## Metodología

Fuentes autorizadas, comparación internacional, revisión y correcciones: [https://{{DOMINIO}}/metodologia](https://{{DOMINIO}}/metodologia).
