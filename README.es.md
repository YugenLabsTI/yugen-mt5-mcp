<!-- mcp-name: io.github.yugenlabsti/yugen-mt5-mcp -->

# yugen-mt5-mcp

> 🌐 **Idioma**: Español | [English](README.md)
>
> 📚 ¿Nuevo en el proyecto? Empieza por el [índice de la documentación](docs/index.md).

Servidor MCP seguro y auditable para MetaTrader 5 — da a los clientes de IA acceso controlado a datos de mercado, estado de la cuenta y ejecución de órdenes a través de una compuerta reforzada con listas blancas de símbolos, límites de volumen y un registro de auditoría de solo escritura (append-only).

## Inicio rápido (para usuarios)

### Requisitos previos

- Windows con MetaTrader 5 instalado y sesión iniciada en una cuenta demo
- [uv](https://docs.astral.sh/uv/getting-started/installation/) instalado

### Ejecutar sin instalar

```powershell
uvx yugen-mt5-mcp
```

### Instalar de forma persistente

```powershell
uv tool install yugen-mt5-mcp
yugen-mt5-mcp
```

### Validar tu configuración

```powershell
yugen-mt5-mcp doctor
```

Esto ejecuta todas las verificaciones de preparación (configuración, conexión a MT5, ruta de auditoría, transporte) sin iniciar el servidor.

---

## Configuración de clientes

> Para la guía completa de conexión que cubre los 4 métodos (STDIO, remoto en LAN, VPS/TLS),
> consulta [docs/es/connection-methods.md](docs/es/connection-methods.md).

### Claude Desktop

Agrega lo siguiente a tu archivo de configuración de Claude Desktop.

- **Windows**: `C:\Users\YOUR_USERNAME\AppData\Roaming\Claude\claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "yugen-mt5": {
      "command": "uvx",
      "args": ["yugen-mt5-mcp"],
      "env": {
        "YUGEN_MT5_ALLOWED_SYMBOLS": "EURUSD,XAUUSD",
        "YUGEN_MT5_ALLOW_LIVE_TRADING": "false",
        "YUGEN_MT5_ALLOW_REAL_ACCOUNTS": "false",
        "YUGEN_MT5_MAX_ORDER_VOLUME": "1.0",
        "YUGEN_MT5_MAX_SYMBOL_EXPOSURE": "1.0",
        "YUGEN_MT5_AUDIT_PATH": "C:\\Users\\YOUR_USERNAME\\AppData\\Local\\Yugen\\mt5-mcp\\audit.sqlite3"
      }
    }
  }
}
```

También puedes generar este bloque automáticamente:

```powershell
yugen-mt5-mcp config claude
```

### Cursor

Agrega lo siguiente a `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "yugen-mt5": {
      "command": "uvx",
      "args": ["yugen-mt5-mcp"],
      "env": {
        "YUGEN_MT5_ALLOWED_SYMBOLS": "EURUSD,XAUUSD",
        "YUGEN_MT5_ALLOW_LIVE_TRADING": "false",
        "YUGEN_MT5_ALLOW_REAL_ACCOUNTS": "false",
        "YUGEN_MT5_MAX_ORDER_VOLUME": "1.0",
        "YUGEN_MT5_MAX_SYMBOL_EXPOSURE": "1.0"
      }
    }
  }
}
```

```powershell
yugen-mt5-mcp config cursor
```

### OpenCode

Agrega lo siguiente a `~/.config/opencode/config.json`:

```json
{
  "mcp": {
    "yugen-mt5": {
      "type": "local",
      "command": ["uvx", "yugen-mt5-mcp"],
      "environment": {
        "YUGEN_MT5_ALLOWED_SYMBOLS": "EURUSD,XAUUSD",
        "YUGEN_MT5_ALLOW_LIVE_TRADING": "false",
        "YUGEN_MT5_ALLOW_REAL_ACCOUNTS": "false",
        "YUGEN_MT5_MAX_ORDER_VOLUME": "1.0",
        "YUGEN_MT5_MAX_SYMBOL_EXPOSURE": "1.0"
      },
      "enabled": true
    }
  }
}
```

```powershell
yugen-mt5-mcp config opencode
```

---

## Configuración (variables de entorno)

Toda la configuración se hace mediante variables de entorno `YUGEN_MT5_*`. Puedes generar un bloque de variables de forma interactiva:

```powershell
yugen-mt5-mcp init
```

| Variable | Requerida | Predeterminado | Descripción |
|----------|-----------|----------------|-------------|
| `YUGEN_MT5_ALLOWED_SYMBOLS` | **Sí** | — | Lista blanca de símbolos separados por comas, o `*` para todos. El comodín imprime una advertencia al inicio pero no relaja ninguna compuerta de trading. |
| `YUGEN_MT5_ALLOW_LIVE_TRADING` | No | `false` | Establece `true` para habilitar la ejecución de órdenes. Cuando es `false`, el servidor es de solo lectura. |
| `YUGEN_MT5_ALLOW_REAL_ACCOUNTS` | No | `false` | Establece `true` para permitir operaciones en cuentas reales (no demo). Las cuentas demo no lo necesitan. |
| `YUGEN_MT5_MAX_ORDER_VOLUME` | No | `1.0` | Volumen máximo en lotes por cada orden individual que crea exposición. No aplica al cerrar o modificar. Usa `unlimited` para deshabilitarlo (advertencia al inicio). |
| `YUGEN_MT5_MAX_SYMBOL_EXPOSURE` | No | `1.0` | Volumen abierto acumulado máximo por símbolo. Se verifica solo al abrir. Usa `unlimited` para deshabilitarlo (advertencia al inicio). |
| `YUGEN_MT5_AUDIT_PATH` | No | `var/audit.sqlite3` | Ruta de la base de datos SQLite de auditoría. Usa una ruta absoluta con clientes de escritorio. |
| `YUGEN_MT5_REAL_ACCOUNT_CONSENT` | No | — | Token de consentimiento explícito para operaciones en cuentas reales. Se reinicia en cada reinicio del servidor. |
| `YUGEN_MT5_REMOTE_ENABLED` | No | `false` | Establece `true` para iniciar el transporte remoto HTTP. Requiere el extra `[remote]`. |
| `YUGEN_MT5_REMOTE_HOST` | No | `127.0.0.1` | Dirección de enlace (bind) del transporte remoto. Usa `0.0.0.0` para LAN/VPS (requiere terminación TLS). |
| `YUGEN_MT5_REMOTE_PORT` | No | `8765` | Puerto del transporte remoto. |
| `YUGEN_MT5_REMOTE_BEARER_TOKEN` | No | — | Token bearer para la autenticación del transporte remoto. Requerido cuando `YUGEN_MT5_REMOTE_ENABLED=true`. |

### Modelo de seguridad de trading

| Control | Comportamiento |
|---------|----------------|
| Reconocimiento de cuenta real | Con alcance de sesión. Se limpia en cada reinicio del servidor. |
| Símbolos permitidos / modos de cuenta | Se aplican antes de las llamadas a MT5. |
| Límites de volumen / exposición | Se aplican solo a órdenes de apertura. Cerrar y modificar nunca tienen tope. |
| Registro de auditoría | Log append-only en SQLite con redacción de tokens y secretos. |

---

## Transporte remoto (WSL / Mac hacia MT5 en Windows)

Cuando tu cliente de IA se ejecuta en WSL, macOS o un VPS y MetaTrader 5 está en un host Windows, usa el transporte remoto HTTP:

```powershell
# En el host Windows:
$env:YUGEN_MT5_REMOTE_ENABLED="true"
$env:YUGEN_MT5_REMOTE_BEARER_TOKEN="your-secret-token"
yugen-mt5-mcp run --transport remote

# Genera un bloque de configuración de cliente apuntando al host Windows:
yugen-mt5-mcp config remote --host 192.168.1.100 --port 8765 --token your-secret-token
```

Instala primero el extra remote:

```powershell
uv tool install "yugen-mt5-mcp[remote]"
```

Consulta [docs/es/remote-transport.md](docs/es/remote-transport.md) para la guía completa de despliegue, el modelo de seguridad y la configuración de TLS.
Para el paso a paso de VPS (EC2 + Caddy/TLS), consulta [docs/es/connection-methods.md — Método 4](docs/es/connection-methods.md#método-4--remoto-vps--caddytls).

---

## Para contribuidores

### Clonar e instalar en modo editable

```powershell
git clone https://github.com/YugenLabsTI/yugen-mt5-mcp.git
cd yugen-mt5-mcp
python -m pip install -e ".[dev]"
```

### Ejecutar la suite de pruebas

```powershell
pytest
```

Las pruebas que dependen de MT5 se omiten automáticamente en plataformas distintas de Windows.

### Ejecutar linting y verificación de tipos

```powershell
ruff check src tests
mypy
```

### Iniciar el servidor localmente

```powershell
$env:YUGEN_MT5_ALLOWED_SYMBOLS="EURUSD,XAUUSD"
yugen-mt5-mcp run
```

Para todas las opciones de la CLI consulta [docs/es/cli.md](docs/es/cli.md). Para las variantes de instalación consulta [docs/es/install.md](docs/es/install.md).

---

## Licencia

Apache-2.0 — consulta [LICENSE.md](LICENSE.md). Copyright Yugen Labs S.A.S.
