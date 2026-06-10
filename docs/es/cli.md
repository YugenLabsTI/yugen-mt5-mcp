# Referencia de la CLI

> 🌐 **Idioma**: Español | [English](../cli.md) · [Volver al índice](../index.md)

```
yugen-mt5-mcp <command> [options]
```

La invocación sin subcomando es idéntica a `yugen-mt5-mcp run` en modo stdio. Las configuraciones de clientes existentes que referencian solo el nombre del script siguen funcionando sin modificaciones.

---

## Comandos

- [`run`](#run) — Iniciar el servidor MCP
- [`doctor`](#doctor) — Ejecutar verificaciones de preparación
- [`config`](#config) — Generar configuración de cliente
- [`init`](#init) — Asistente interactivo de configuración
- [`version`](#version) — Imprimir información de versión

---

## `run`

Inicia el servidor MCP.

```
yugen-mt5-mcp run [OPTIONS]
```

El transporte predeterminado es `stdio`. Usa `--transport remote` para iniciar el transporte HTTP (requiere el extra `[remote]`).

### Opciones

| Flag | Predeterminado | Descripción |
|------|----------------|-------------|
| `--transport`, `-t` | `stdio` | Modo de transporte: `stdio` o `remote`. |
| `--host` | `127.0.0.1` | Dirección de enlace para el transporte remoto. Solo se usa con `--transport remote`. |
| `--port`, `-p` | `8765` | Puerto para el transporte remoto. Solo se usa con `--transport remote`. |
| `--env-file` | _(ninguno)_ | Carga la configuración desde un archivo dotenv en lugar de exportar cada variable a mano. Las variables de entorno reales tienen precedencia sobre el archivo. |

### Códigos de salida

| Código | Significado |
|--------|-------------|
| `0` | El servidor terminó limpiamente. |
| `1` | Valor de transporte inválido, transporte remoto solicitado sin `uvicorn` instalado, o ruta de `--env-file` no encontrada. |

### Ejemplos

```powershell
# Iniciar en modo stdio (predeterminado)
yugen-mt5-mcp run

# Iniciar en modo HTTP remoto en la dirección loopback predeterminada
yugen-mt5-mcp run --transport remote

# Modo remoto en un host y puerto personalizados
yugen-mt5-mcp run --transport remote --host 0.0.0.0 --port 9000

# Cargar la configuración desde un archivo dotenv (cambiar fácilmente entre perfiles demo/real)
yugen-mt5-mcp run --env-file ./demo.env
```

> **Nota de producción:** al ejecutar como servicio en un VPS, es preferible que el
> gestor de procesos inyecte el entorno (systemd `EnvironmentFile=`, o
> `docker run --env-file`) en lugar de `--env-file`. Mantén los archivos env con secretos en
> `chmod 600` y nunca los subas al repositorio.

Instala el extra remote antes de usar `--transport remote`:

```powershell
pip install "yugen-mt5-mcp[remote]"
```

---

## `doctor`

Ejecuta todas las verificaciones de preparación sin iniciar el servidor MCP.

```
yugen-mt5-mcp doctor [OPTIONS]
```

Las verificaciones se ejecutan en este orden: `platform` → `config` → `audit_path` → `runtime_context` → `remote_transport` → `mt5_connection` → `mt5_account` → `real_account_consent`.

En plataformas distintas de Windows, `mt5_connection` y `mt5_account` se reportan como `SKIPPED` (no `FAILED`). Todas las demás verificaciones se ejecutan en todas las plataformas.

### Opciones

| Flag | Predeterminado | Descripción |
|------|----------------|-------------|
| `--json` | `false` | Emite JSON legible por máquina en lugar de una tabla legible por humanos. |

### Códigos de salida

| Código | Significado |
|--------|-------------|
| `0` | Todas las verificaciones pasaron (WARN y SKIPPED no afectan el código de salida). |
| `1` | Una o más verificaciones devolvieron `FAIL`. |

### Ejemplos

```powershell
# Salida legible por humanos
yugen-mt5-mcp doctor

# JSON legible por máquina (útil para scripting)
yugen-mt5-mcp doctor --json
```

### Salida de ejemplo

```
yugen-mt5-mcp doctor — 2026-06-03 12:00:00 UTC

  platform              [OK     ]  Running on Windows
  config                [OK     ]  Configuration loaded
  audit_path            [OK     ]  Audit path is writable
  runtime_context       [OK     ]  Runtime context is valid
  remote_transport      [OK     ]  Remote transport not enabled
  mt5_connection        [OK     ]  MT5 terminal connected
  mt5_account           [OK     ]  Account info retrieved
  real_account_consent  [OK     ]  Demo account — no consent required

Overall: OK
```

---

## `config`

Genera un bloque de configuración de cliente MCP listo para pegar.

```
yugen-mt5-mcp config <client> [OPTIONS]
```

La salida va a stdout de forma predeterminada. Usa `--output <path>` para escribir a un archivo.

No se incluyen rutas personales ni credenciales reales — los valores de las variables de entorno son marcadores de posición genéricos que tú completas.

### Subcomandos

#### `config claude`

Imprime el bloque de configuración `mcpServers` para Claude Desktop.

```
yugen-mt5-mcp config claude [OPTIONS]
```

Fusiona la salida en:
- **Windows**: `C:\Users\YOUR_USERNAME\AppData\Roaming\Claude\claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

| Flag | Predeterminado | Descripción |
|------|----------------|-------------|
| `--version`, `-v` | latest | Fija el paquete a una versión específica (p. ej. `0.1.0`). |
| `--output`, `-o` | stdout | Escribe el JSON a un archivo en lugar de imprimirlo. |

```powershell
yugen-mt5-mcp config claude
yugen-mt5-mcp config claude --version 0.1.0
yugen-mt5-mcp config claude --output claude_config.json
```

#### `config cursor`

Imprime el bloque de configuración `mcpServers` para Cursor (mismo esquema que Claude Desktop).

```
yugen-mt5-mcp config cursor [OPTIONS]
```

Fusiónalo en `~/.cursor/mcp.json`.

| Flag | Predeterminado | Descripción |
|------|----------------|-------------|
| `--version`, `-v` | latest | Fija la versión del paquete. |
| `--output`, `-o` | stdout | Escribe a un archivo. |

```powershell
yugen-mt5-mcp config cursor
yugen-mt5-mcp config cursor --output ~/.cursor/mcp.json
```

#### `config opencode`

Imprime el bloque de configuración `mcp` para OpenCode.

```
yugen-mt5-mcp config opencode [OPTIONS]
```

Fusiónalo en `~/.config/opencode/config.json` (o `opencode.json` en la raíz del proyecto).

| Flag | Predeterminado | Descripción |
|------|----------------|-------------|
| `--version`, `-v` | latest | Fija la versión del paquete. |
| `--output`, `-o` | stdout | Escribe a un archivo. |

```powershell
yugen-mt5-mcp config opencode
```

#### `config remote`

Imprime un bloque de configuración para el transporte remoto HTTP con un marcador de posición de token bearer.

```
yugen-mt5-mcp config remote [OPTIONS]
```

Úsalo cuando el cliente MCP se conecta a un servidor yugen-mt5-mcp que corre en otra máquina (p. ej. desde WSL o macOS hacia un host Windows con MT5).

| Flag | Predeterminado | Descripción |
|------|----------------|-------------|
| `--host` | `127.0.0.1` | Host del servidor remoto. |
| `--port` | `8765` | Puerto del servidor remoto. |
| `--token` | `<BEARER_TOKEN>` | Marcador de posición del token bearer. |
| `--output`, `-o` | stdout | Escribe a un archivo. |

```powershell
yugen-mt5-mcp config remote
yugen-mt5-mcp config remote --host 192.168.1.100 --port 8765 --token my-secret-token
```

### Códigos de salida

| Código | Significado |
|--------|-------------|
| `0` | Configuración impresa o escrita correctamente. |
| `1` | Cliente desconocido o error de escritura. |

---

## `init`

Asistente interactivo para generar un bloque de variables de entorno `YUGEN_MT5_*`.

```
yugen-mt5-mcp init [OPTIONS]
```

Pregunta por: símbolos permitidos, modo demo/live, permiso de cuenta real, volumen máximo por orden, exposición máxima por símbolo y ruta de auditoría. NO requiere que MetaTrader 5 esté conectado.

### Opciones

| Flag | Predeterminado | Descripción |
|------|----------------|-------------|
| `--json` | `false` | Emite JSON en lugar de pares `KEY=VALUE`. |
| `--output`, `-o` | stdout | Escribe la salida a un archivo (p. ej. `.env`). |

### Códigos de salida

| Código | Significado |
|--------|-------------|
| `0` | El asistente terminó y la salida fue impresa o escrita. |
| `1` | El usuario canceló o hubo error de escritura. |

### Ejemplos

```powershell
# Asistente interactivo, imprime a stdout
yugen-mt5-mcp init

# Escribe el bloque env a un archivo .env
yugen-mt5-mcp init --output .env

# Salida JSON
yugen-mt5-mcp init --json
```

### Salida de ejemplo

```
YUGEN_MT5_ALLOWED_SYMBOLS=EURUSD,XAUUSD
YUGEN_MT5_ALLOW_LIVE_TRADING=false
YUGEN_MT5_ALLOW_REAL_ACCOUNTS=false
YUGEN_MT5_MAX_ORDER_VOLUME=1.0
YUGEN_MT5_MAX_SYMBOL_EXPOSURE=1.0
```

---

## `version`

Imprime la versión del paquete, la versión de Python e información de la plataforma.

```
yugen-mt5-mcp version
```

En Windows con MT5 conectado, también imprime la información del build de la terminal MT5.

### Códigos de salida

| Código | Significado |
|--------|-------------|
| `0` | Siempre. |

### Salida de ejemplo

```
yugen-mt5-mcp 0.1.0
Python 3.12.3 (main, ...) [MSC v.1940 64 bit (AMD64)]
Platform Windows-11-10.0.26100
MetaTrader5 terminal: C:\Program Files\MetaTrader 5\terminal64.exe (build 4755)
```
