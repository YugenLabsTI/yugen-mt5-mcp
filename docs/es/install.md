# Instalación

> 🌐 **Idioma**: Español | [English](../install.md) · [Volver al índice](../index.md)

Esta página cubre todos los métodos de instalación soportados para `yugen-mt5-mcp`.

## Requisitos

- Python 3.11 o 3.12
- Windows (requerido para la conectividad con MetaTrader 5 — el servidor se instala e inicia en otras plataformas, pero las herramientas que dependen de MT5 no estarán disponibles)
- Terminal de MetaTrader 5 abierta y con sesión iniciada antes de iniciar el servidor

---

## Opción 1: Ejecutar sin instalar (recomendada para el primer uso)

[uv](https://docs.astral.sh/uv/getting-started/installation/) ejecuta el paquete directamente desde PyPI en un entorno aislado — no se necesita paso de instalación.

```powershell
uvx yugen-mt5-mcp
```

El paquete se descarga en la primera ejecución y se guarda en caché para las siguientes. Usa esta opción para una evaluación rápida o cuando no quieras una instalación persistente.

---

## Opción 2: Instalar de forma persistente con uv

```powershell
uv tool install yugen-mt5-mcp
```

Después de esto, `yugen-mt5-mcp` queda disponible como comando global. Actualiza con:

```powershell
uv tool upgrade yugen-mt5-mcp
```

---

## Opción 3: Instalar con pip

```powershell
pip install yugen-mt5-mcp
```

O fijando una versión:

```powershell
pip install "yugen-mt5-mcp==0.1.0"
```

---

## Opción 4: Instalar con soporte de transporte remoto

El transporte remoto HTTP (para clientes en WSL, macOS o VPS que se conectan a un MT5 en Windows) requiere el extra `[remote]`, que instala `uvicorn`.

```powershell
pip install "yugen-mt5-mcp[remote]"
```

O con uv:

```powershell
uv tool install "yugen-mt5-mcp[remote]"
```

---

## Notas por plataforma

### Windows

`MetaTrader5` se instala automáticamente como dependencia en Windows (`sys_platform == 'win32'`). No se necesita ningún paso manual.

### Linux / macOS

`MetaTrader5` no se instala en plataformas distintas de Windows (el marcador de plataforma lo excluye). Los comandos de la CLI `doctor`, `config`, `init` y `version` funcionan con normalidad. Las verificaciones del doctor que dependen de MT5 (`mt5_connection`, `mt5_account`) reportan `SKIPPED`.

---

## Verificar la instalación

```powershell
yugen-mt5-mcp doctor
```

Esto ejecuta todas las verificaciones de preparación sin iniciar el servidor. Una salida saludable se ve así:

```
yugen-mt5-mcp doctor — 2026-06-03 12:00:00 UTC

  platform            [OK     ]  Running on Windows
  config              [OK     ]  Configuration loaded
  audit_path          [OK     ]  Audit path is writable
  runtime_context     [OK     ]  Runtime context is valid
  remote_transport    [OK     ]  Remote transport not enabled
  mt5_connection      [OK     ]  MT5 terminal connected
  mt5_account         [OK     ]  Account info retrieved
  real_account_consent [OK    ]  Demo account — no consent required

Overall: OK
```

---

## Próximos pasos

- Consulta [cli.md](cli.md) para todos los comandos y opciones de la CLI.
- Consulta [remote-transport.md](remote-transport.md) para la configuración del transporte remoto.
- Consulta el [README](../../README.es.md) para la configuración de clientes (Claude Desktop, Cursor, OpenCode).
