# tor_proxy — módulo aislado de rotación de IP vía Tor

Copia independiente del módulo `scraper/proxy_pool.py` del CNMC scraper, lista
para reutilizar en otro desarrollo. No es un servidor proxy: controla un demonio
**Tor** local mediante la librería `stem` y le pide cambiar de IP (señal
`NEWNYM`) de forma automática (cada N operaciones exitosas) o forzada.

## Contenido

```
tor_proxy/
├── __init__.py        # Exporta ProxyPool y load_config
├── proxy_pool.py      # El módulo (copia íntegra, sin cambios de comportamiento)
├── utils.py           # load_config() — carga de YAML
├── config.yaml        # Configuración (proxy + rotation_count)
├── example_usage.py   # Ejemplo de integración
├── requirements.txt   # stem, pyyaml
└── README.md
```

## Requisitos previos

1. **Python 3.10+** y dependencias:
   ```bash
   pip install -r tor_proxy/requirements.txt   # o: uv add stem pyyaml
   ```

2. **Demonio Tor local** con puerto de control habilitado. Edita tu `torrc`
   (p. ej. `sudo nano /etc/tor/torrc`):
   ```
   ControlPort 9051
   HashedControlPassword <hash>
   ```
   Genera el hash con:
   ```bash
   tor --hash-password "scraper"
   ```
   y reinicia Tor (`sudo systemctl restart tor`). El password debe coincidir
   con `proxy.control_password` en `config.yaml`.

3. Verifica que Tor escucha: SOCKS en `127.0.0.1:9050` y control en `9051`.

## Integración en otro proyecto

1. Copia la carpeta `tor_proxy/` a la raíz de tu proyecto (o a tu `src/`).
2. Copia `config.yaml` a tu directorio de trabajo, o pasa tu propio dict de
   configuración a `ProxyPool`.
3. Importa y usa:

```python
from tor_proxy import ProxyPool, load_config

config = load_config("config.yaml")  # dict con secciones "proxy" y "scraping"
pool = ProxyPool(config)
pool.connect()                       # verifica el puerto de control al arrancar

# En tu cliente HTTP/navegador, usa el proxy SOCKS5:
socks_url = pool.get_socks_proxy()   # "socks5://127.0.0.1:9050"

# Rotación por contador (cada rotation_count éxitos):
if pool.rotate_if_needed(success_count):
    ...  # p. ej. rotar también user-agent

# Rotación inmediata ante bloqueo/captcha/429:
pool.force_rotate()
```

Ejemplo completo ejecutable: `python tor_proxy/example_usage.py`.

### Ejemplo con Playwright

```python
proxy = {"server": pool.get_socks_proxy()}
browser = await playwright.chromium.launch(proxy=proxy, headless=True)
```

### Ejemplo con requests

```python
proxies = {"http": pool.get_socks_proxy(), "https": pool.get_socks_proxy()}
r = requests.get(url, proxies=proxies, timeout=30)
```

## Configuración (`config.yaml`)

| Clave                        | Por defecto     | Descripción                                        |
| ---------------------------- | --------------- | -------------------------------------------------- |
| `proxy.tor_host`             | `127.0.0.1`     | Host del SOCKS5 de Tor                             |
| `proxy.tor_port`             | `9050`          | Puerto SOCKS5                                      |
| `proxy.control_port`         | `9051`          | Puerto de control (señales)                        |
| `proxy.control_password`     | `scraper`       | Password del puerto de control                     |
| `scraping.rotation_count`    | `9`             | Rota la IP cada N llamadas exitosas a `rotate_if_needed` |

También puedes construir el dict a mano sin YAML:

```python
config = {
    "proxy": {"tor_host": "127.0.0.1", "tor_port": 9050,
              "control_port": 9051, "control_password": "scraper"},
    "scraping": {"rotation_count": 9},
}
pool = ProxyPool(config)
```

## API de `ProxyPool`

| Método                        | Descripción                                                                 |
| ----------------------------- | --------------------------------------------------------------------------- |
| `connect()`                   | Comprueba autenticación contra el puerto de control (llamar al iniciar)      |
| `get_socks_proxy() -> str`    | Devuelve la URL SOCKS5 (`socks5://host:port`) para tu cliente                |
| `rotate_if_needed(n) -> bool` | Si `n` es múltiplo de `rotation_count`, rota y devuelve `True`               |
| `force_rotate()`              | Rota la IP inmediatamente (bloqueos, captchas)                               |
| `reset_counter()`             | Reinicia el contador interno                                                 |

## Comportamiento y limitaciones

- La rotación envía `NEWNYM` a Tor; entre rotaciones se respeta una espera
  mínima de **10 s** (`MIN_ROTATION_WAIT` en `proxy_pool.py`), porque Tor
  tarda ~10 s en construir un circuito nuevo. Si rotas más rápido, la llamada
  se bloquea (sleep) hasta cumplir la espera.
- **`NEWNYM` solo afecta a conexiones NUEVAS.** Las conexiones ya establecidas
  conservan el circuito/IP anterior. En navegadores con conexiones persistentes
  (keep-alive), para que la nueva IP sea efectiva puede ser necesario abrir un
  contexto/página nueva tras rotar.
- Los fallos de conexión/rotación se registran con `logging` (niveles
  `error`/`warning`) pero **no lanzan excepciones**: el módulo degrada con
  elegancia y sigue operando con la IP actual.
- El módulo es síncrono y seguro para usar desde código async (las llamadas a
  `stem` son breves; la espera de 10 s en `_rotate` sí bloquea el event loop,
  tenlo en cuenta si rotas dentro de `asyncio`).

## Nota sobre el proyecto original

Esta carpeta es una copia aislada; el scraper original (`scraper/proxy_pool.py`)
no ha sido modificado y sigue usando su propio `config.yaml` en la raíz.
