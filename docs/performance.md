# Performance y cache

Cómo aprovechar el paralelismo, el cache compartido y los reintentos automáticos para acelerar tus consultas.

## Descargas paralelas

Las llamadas SOAP a SMV son lentas (~9 segundos cada una). La librería **descarga en paralelo** (10 workers por default) para acelerar consultas multi-año:

| Escenario | Cold cache | Warm cache |
|---|---|---|
| 10 años trimestrales (1 ticker) | ~2 min | <1s |
| Modo serial (`max_workers=1`) | ~20 min | <1s |
| Multi-empresa (10 tickers, mismo rango) | ~2 min total | <1s |

```python
# Default: 10 workers en paralelo
datos = fetch_eeff("ALICORC1", desde=2016, hasta=2025, periodicidad="trimestral")

# Para descargas secuenciales (modo legacy):
datos = fetch_eeff("ALICORC1", desde=2023, hasta=2023, max_workers=1)
```

`max_workers` está limitado a un máximo de 10 para no saturar el web service de SMV.

## Cache local comprimido

El cache local se almacena con compresión gzip (extensión `.json.gz`). Reduce ~96% el tamaño en disco vs JSON crudo, sin penalizar velocidad de lectura (la menor I/O compensa el costo CPU de descompresión).

| Métrica | Sin compresión | Con gzip |
|---|---|---|
| 10 años × 27 empresas | ~1 GB | ~50 MB |

> [!NOTE]
> Si tienes archivos `.json` de versiones anteriores, se leen sin problema (compatibilidad retroactiva). Solo se escribe en `.json.gz`.

### Ubicación del cache

Por defecto: cache del usuario según el SO.

- **macOS**: `~/Library/Caches/smv-peru/`
- **Linux**: `~/.cache/smv-peru/`
- **Windows**: `%LOCALAPPDATA%\smv-peru\Cache\`

Configurable vía:
- Argumento `cache_dir=` en `fetch_eeff` y `fetch_multi`.
- Variable de entorno `SMV_PERU_CACHE_DIR`.

### Escritura atómica

El cache usa write-to-temp + `os.replace()`. Soporta uso concurrente de varios procesos compartiendo el mismo `cache_dir` sin riesgo de corrupción.

## Cache compartido entre empresas

> [!IMPORTANT]
> Una sola call SOAP a SMV devuelve **todas las empresas peruanas** para ese
> `(operación, año, periodo, tipo)`. Una vez cacheado para 1 ticker, los demás
> son ~gratis.

```python
# Primera empresa: ~2 min (cold cache)
fetch_eeff("ALICORC1", desde=2020, hasta=2024)

# Siguientes empresas mismo rango: <1s cada una
fetch_eeff("BACKUSI1", desde=2020, hasta=2024)
fetch_eeff("UNACEMC1", desde=2020, hasta=2024)
```

Para descargar varios tickers eficientemente, usar `fetch_multi` (ver abajo).

## Multi-empresa con `fetch_multi`

```python
from smv_peru import fetch_multi

# Descarga un sector de una vez (cache compartido = más rápido que loop)
sectorial = fetch_multi(
    ["CPACASC1", "UNACEMC1", "YURAC1"],
    desde=2019, hasta=2024,
)
# sectorial == {"CPACASC1": {...}, "UNACEMC1": {...}, "YURAC1": {...}}

# Tickers inválidos quedan como None sin abortar el resto
sectorial = fetch_multi(["ALICORC1", "TICKER_INVALIDO"], desde=2023, hasta=2023)
# sectorial["ALICORC1"] tiene datos; sectorial["TICKER_INVALIDO"] es None
```

`to_excel` y `to_csv` detectan automáticamente single vs multi-empresa: con multi, generan una hoja por ticker (Excel) o secciones por ticker (CSV).

## Reintentos automáticos

Las llamadas SOAP fallidas por timeouts o errores de red se reintentan automáticamente hasta **3 veces con backoff exponencial**.

> [!NOTE]
> Errores definitivos (ej. respuesta sin formato esperado) **no** se reintentan
> — probablemente los datos no existen y reintentar solo demoraría.
