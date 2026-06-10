# Métodos de conexión

> 🌐 **Idioma**: Español | [English](../connection-methods.md) · [Volver al índice](../index.md)

Esta guía explica cómo conectar un cliente de IA (Claude Desktop, Cursor, OpenCode o Claude Code)
a un servidor yugen-mt5-mcp en ejecución. Elige en la tabla de abajo el método que corresponda a tu configuración.

## Resumen

| Método | Para quién es | Transporte | Conexión | Profundizar |
|--------|---------------|------------|----------|-------------|
| [1. STDIO vía instalación editable](#método-1--stdio-vía-instalación-editable) | Contribuidores / desarrolladores | stdio | Solo local | [install.md](install.md) |
| [2. STDIO vía uvx](#método-2--stdio-vía-uvx) | La mayoría de usuarios (Claude Desktop, Cursor, OpenCode) | stdio | Solo local | [install.md](install.md), [cli.md](cli.md) |
| [3. Remoto — host Windows + agente WSL/macOS](#método-3--remoto-host-windows--agente-wslmacos) | Misma red: agente WSL + MT5 en Windows | HTTP | LAN / loopback | [remote-transport.md](remote-transport.md) |
| [4. Remoto — VPS + Caddy/TLS](#método-4--remoto-vps--caddytls) | Despliegue público / en la nube | HTTPS | Internet | [remote-transport.md](remote-transport.md) |

---

## Método 1 — STDIO vía instalación editable

> **Ruta de contribuidor / desarrollador.** Este método está pensado para quienes han clonado el
> repositorio y quieren ejecutar el servidor directamente desde el árbol de código fuente. No es la ruta
> recomendada para uso general — para eso consulta el [Método 2](#método-2--stdio-vía-uvx).

### Requisitos previos

- Python 3.11 o 3.12 en Windows
- Terminal de MetaTrader 5 abierta y con sesión iniciada en una cuenta demo
- Repositorio clonado localmente

### Configuración

```powershell
git clone https://github.com/YugenLabsTI/yugen-mt5-mcp.git
cd yugen-mt5-mcp
python -m pip install -e ".[dev]"
```

### Iniciar el servidor

Crea un archivo `.env` con tu configuración (consulta [Apéndice de referencia — Variables de entorno](#variables-de-entorno)), luego:

```powershell
yugen-mt5-mcp run --env-file .env
```

> **Detalle con AUDIT_PATH:** los clientes de escritorio (Claude Desktop, Cursor, OpenCode) lanzan el servidor
> desde su propio directorio de trabajo, lo que hace que rutas relativas como `var/audit.sqlite3` se resuelvan
> en una ubicación inesperada. Usa una ruta absoluta para `YUGEN_MT5_AUDIT_PATH` en cualquier archivo `.env`
> que uses con un cliente de escritorio. Consulta la [advertencia de AUDIT_PATH](#advertencia-de-audit_path) en el apéndice.

### Configuración del cliente

Usa los mismos bloques JSON de cliente que en el [Método 2](#método-2--stdio-vía-uvx) pero reemplaza
`command` / `args` con el nombre del script local:

```json
{
  "mcpServers": {
    "yugen-mt5": {
      "command": "yugen-mt5-mcp",
      "args": [],
      "env": {
        "YUGEN_MT5_ALLOWED_SYMBOLS": "EURUSD,XAUUSD",
        "YUGEN_MT5_ALLOW_LIVE_TRADING": "false",
        "YUGEN_MT5_ALLOW_REAL_ACCOUNTS": "false",
        "YUGEN_MT5_AUDIT_PATH": "C:\\absolute\\path\\to\\audit.sqlite3"
      }
    }
  }
}
```

Para la matriz completa de opciones de instalación, consulta [install.md](install.md). Para la configuración
del entorno de desarrollo y las pautas de contribución, consulta la
[sección de contribuidores en el README](../../README.es.md#para-contribuidores).

---

## Método 2 — STDIO vía uvx

> **Ruta principal de usuario.** Si no eres un desarrollador trabajando desde el código fuente, empieza aquí.

### Requisitos previos

- Windows con MetaTrader 5 instalado y sesión iniciada en una cuenta demo
- [uv](https://docs.astral.sh/uv/getting-started/installation/) instalado

### Cómo funciona

`uvx` ejecuta el paquete directamente desde PyPI en un entorno aislado — no se necesita un paso de instalación
separado. El paquete se guarda en caché después de la primera ejecución.

### Configuración del cliente

Elige el bloque de tu cliente, fusiónalo en el archivo de configuración indicado y reinicia el cliente.

#### Claude Desktop

Ubicaciones del archivo de configuración:
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

Genera este bloque automáticamente:

```powershell
yugen-mt5-mcp config claude
```

#### Cursor

Archivo de configuración: `~/.cursor/mcp.json`

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

Auto-generar:

```powershell
yugen-mt5-mcp config cursor
```

#### OpenCode

Archivo de configuración: `~/.config/opencode/config.json` (u `opencode.json` en la raíz del proyecto)

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
        "YUGEN_MT5_MAX_SYMBOL_EXPOSURE": "1.0",
        "YUGEN_MT5_AUDIT_PATH": "C:\\Users\\YOUR_USERNAME\\AppData\\Local\\Yugen\\mt5-mcp\\audit.sqlite3"
      },
      "enabled": true
    }
  }
}
```

Auto-generar:

```powershell
yugen-mt5-mcp config opencode
```

> **AUDIT_PATH:** Los clientes de escritorio ejecutan el servidor en su propio directorio de trabajo. Usa siempre
> una ruta absoluta para `YUGEN_MT5_AUDIT_PATH`. Consulta la [advertencia de AUDIT_PATH](#advertencia-de-audit_path).

Para la referencia completa de flags de la CLI, consulta [cli.md](cli.md).

---

## Método 3 — Remoto (host Windows + agente WSL/macOS)

Usa este método cuando MetaTrader 5 corre en un host Windows y tu agente de IA (Claude Code,
OpenCode, etc.) corre en WSL o en una máquina macOS en la misma red.

### Arquitectura

```
  Agente WSL / macOS                   Host Windows
  ┌────────────────┐                   ┌──────────────────────────┐
  │ Claude Code /  │  HTTP + Bearer    │  yugen-mt5-mcp (remote)  │
  │  OpenCode      │ ────────────────► │  127.0.0.1 o IP LAN      │
  └────────────────┘                   │         │                 │
                                       │         ▼                 │
                                       │   Terminal MT5 (IPC)     │
                                       └──────────────────────────┘
```

### Redes: WSL espejada vs NAT

**Red espejada de WSL (Windows 11 22H2+, recomendada):** Habilítala en `.wslconfig`,
ejecuta `wsl --shutdown` y luego reinicia WSL:

```ini
[wsl2]
networkingMode=mirrored
```

Luego mantén el servidor en su bind de loopback predeterminado y apunta el agente de WSL a
`http://127.0.0.1:8765/mcp/`.

**Modo NAT de WSL o macOS:** Enlaza el servidor a la IP LAN de Windows en su lugar. Para la subred NAT,
la búsqueda de la dirección del host y los detalles de la lista blanca, consulta
[remote-transport.md — Interoperabilidad WSL / Windows](remote-transport.md#interoperabilidad-wsl--windows).

### Pasos

**1. Genera un token bearer** (en el host Windows):

Consulta [Generación de tokens](#generación-de-tokens) en el apéndice.

**2. Inicia el servidor en Windows** (PowerShell):

```powershell
$env:YUGEN_MT5_REMOTE_ENABLED       = "true"
$env:YUGEN_MT5_REMOTE_HOST          = "192.168.1.100"   # tu IP LAN de Windows; usa 127.0.0.1 para WSL espejada
$env:YUGEN_MT5_REMOTE_PORT          = "8765"
$env:YUGEN_MT5_REMOTE_BEARER_TOKEN  = "<YOUR_TOKEN>"
$env:YUGEN_MT5_ALLOWED_SYMBOLS      = "EURUSD,XAUUSD"

yugen-mt5-mcp run --transport remote
```

Para el extra `[remote]` (requerido para el transporte HTTP):

```powershell
uv tool install "yugen-mt5-mcp[remote]"
```

**3. Verifica la postura del servidor** (en Windows):

```powershell
yugen-mt5-mcp doctor
```

Consulta [Verificación con doctor](#verificación-con-doctor) en el apéndice. Para un bind RFC 1918, la
salida esperada es `remote_transport [OK]` — el token por sí solo es suficiente (nivel trusted-local,
TLS no requerido).

**4. Genera la configuración del cliente** (ejecutable en cualquier máquina):

```bash
yugen-mt5-mcp config remote --host 192.168.1.100 --port 8765 --token <YOUR_TOKEN>
```

Esto emite:

```json
{
  "mcpServers": {
    "yugen-mt5-remote": {
      "url": "http://192.168.1.100:8765/mcp/",
      "headers": { "Authorization": "Bearer <YOUR_TOKEN>" }
    }
  }
}
```

El esquema se infiere automáticamente: las direcciones RFC 1918 y loopback producen `http://`;
las IPs públicas producen `https://`. Usa `--scheme http|https` para sobrescribirlo.

**5. Verifica la conectividad** (desde la máquina del agente):

Consulta [Verificación con curl](#verificación-con-curl) en el apéndice.

### Profundizar

Para el modelo de niveles de confianza, la mecánica de la lista blanca con XFF, los detalles de la subred NAT
de WSL y las alternativas nginx/Cloudflare, consulta [remote-transport.md](remote-transport.md).

---

## Método 4 — Remoto (VPS + Caddy/TLS)

Usa este método para un despliegue público en la nube o expuesto a internet, donde el agente de IA se conecta
desde cualquier lugar, no solo desde tu red local.

### Arquitectura

Tres hechos a tener presentes antes de empezar:

1. **La terminal MT5 y el servidor (`run`) viven en el mismo VPS Windows.** El paquete de Python
   `MetaTrader5` se comunica con la terminal mediante IPC de Windows (named pipes). No hay
   forma de ejecutar el servidor en una máquina separada de la terminal.

2. **Tu cliente de IA (Claude Code, OpenCode) corre en tu máquina personal.** Solo necesita
   ser un cliente HTTP que apunte a la URL del VPS con un token bearer. No se requiere instalar MT5
   en la máquina cliente.

3. **El servidor nunca hace TLS por sí mismo.** Siempre habla HTTP plano. Caddy, corriendo en el
   mismo VPS, termina HTTPS y reenvía HTTP plano a `127.0.0.1:8765`.

```
  Tu máquina personal                        VPS (Windows, AWS EC2)
  ┌──────────────────────┐                  ┌────────────────────────────────────────┐
  │ Claude Code /        │  HTTPS ────────► │ Caddy (TLS) ──HTTP──► yugen-mt5-mcp   │
  │ OpenCode             │                  │               127.0.0.1:8765            │
  └──────────────────────┘                  │                    │                    │
                                            │                    ▼                    │
                                            │           Terminal MT5 (IPC)           │
                                            └────────────────────────────────────────┘
```

### Requisitos previos

- Cuenta de AWS (o equivalente) con permisos para crear instancias EC2
- Una cuenta MT5 **demo** (login del bróker, contraseña, nombre del servidor). Nunca uses una cuenta real para
  la configuración inicial.
- Un dominio o subdominio que puedas apuntar al VPS mediante un registro DNS A (requerido para el TLS
  de Let's Encrypt en la Fase B)
- Tu cliente de IA (Claude Code, OpenCode) instalado en tu máquina personal

### Configuración de EC2

**1. Lanza una instancia EC2:**

- AMI: *Microsoft Windows Server 2022 Base*
- Tipo de instancia: `t3.medium` (mínimo — MT5 + Caddy + servidor juntos lo necesitan)
- Par de claves: crea uno nuevo (p. ej. `yugen-vps.pem`) y guárdalo; lo necesitarás para recuperar
  la contraseña de Administrator
- Security Group: crea `yugen-mt5-sg` con **RDP (puerto 3389) restringido únicamente a tu IP**.
  No abras el puerto 8765 todavía — eso sucede en la Fase A.
- Almacenamiento: 50 GB gp3

**2. Asigna una Elastic IP:** EC2 → Elastic IPs → Allocate → Associate a tu instancia.
Esto te da una IP pública estable para el DNS y la lista blanca del cliente. Anótala como `ELASTIC_IP`.

**3. Recupera la contraseña de Administrator:** EC2 → selecciona la instancia → Connect → RDP client →
Get password → sube tu archivo `.pem` → Decrypt. Anota el usuario `Administrator` y la contraseña.

**4. Prepara el VPS:** Conéctate vía RDP (`mstsc` o cualquier cliente RDP) usando `ELASTIC_IP` +
Administrator + contraseña. Abre **PowerShell como Administrador**:

```powershell
# Instala uv (gestor de Python recomendado)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
# Cierra y vuelve a abrir PowerShell para que la actualización del PATH surta efecto.

# Instala yugen-mt5-mcp con el extra remote (incluye uvicorn)
uv tool install "yugen-mt5-mcp[remote]"

# Verifica
yugen-mt5-mcp version
```

Para métodos de instalación alternativos, consulta [install.md](install.md).

**5. Instala y configura MetaTrader 5:** Descarga el instalador de MT5 de tu bróker, instálalo
en el VPS, abre la terminal e inicia sesión en tu **cuenta demo**. La terminal debe permanecer
abierta y con sesión iniciada mientras el servidor corre — si se cierra, la conexión IPC muere. Habilita
el inicio de sesión automático en la cuenta demo para que sobreviva reinicios.

### Fase A — Prueba con HTTP plano

> **Propósito:** Verificar el flujo de conexión completo antes de agregar la complejidad de TLS. Esta fase expone
> HTTP plano a internet con el token en texto claro. Es intencional y temporal.
> Desmóntala inmediatamente después de confirmar la conectividad.

**1. Obtén la IP pública de tu máquina personal** (ejecuta esto en tu máquina, no en el VPS):

```bash
curl ifconfig.me
# Resultado de ejemplo: 200.123.45.67  →  esta es YOUR_PUBLIC_IP
```

Si tu conexión a internet usa una IP dinámica, puede cambiar. Actualiza la lista blanca y la regla del Security
Group si eso sucede.

**2. Abre el puerto 8765 en ambas capas de firewall.**

> **Detalle crítico — dos capas de firewall:** Abrir el puerto en el Security Group de AWS permite que el
> paquete llegue a la instancia EC2, pero **Windows Defender Firewall lo descarta silenciosamente** a menos que
> también agregues una regla de entrada para el puerto 8765. Windows bloquea puertos no estándar por defecto. El
> síntoma es un **timeout de conexión** (no "connection refused") incluso cuando el servidor está
> escuchando en `0.0.0.0:8765`. Si solo abres el Security Group y olvidas la regla del Windows
> Firewall, pasarás mucho tiempo depurando un servidor que está sano.

*Capa 1 — Security Group de AWS:* EC2 → Security Groups → `yugen-mt5-sg` → Inbound rules → Edit:

- Agrega la regla: Custom TCP, puerto `8765`, origen `YOUR_PUBLIC_IP/32`. Nunca uses `0.0.0.0/0` aquí.

*Capa 2 — Windows Defender Firewall* (PowerShell como Admin, dentro del VPS):

```powershell
New-NetFirewallRule -DisplayName "Yugen MCP 8765" -Direction Inbound -Protocol TCP -LocalPort 8765 -Action Allow
```

Diagnóstico: `Get-NetTCPConnection -LocalPort 8765 -State Listen` confirma que el servidor está
escuchando. `Get-NetFirewallRule -Direction Inbound -Enabled True | Get-NetFirewallPortFilter | Where-Object LocalPort -eq 8765` confirma que la regla de firewall existe. Una salida vacía del segundo comando significa que la regla de firewall es el problema.

**3. Genera un token bearer** (en el VPS):

Consulta [Generación de tokens](#generación-de-tokens) en el apéndice.

**4. Inicia el servidor** (PowerShell en el VPS):

```powershell
$env:YUGEN_MT5_ALLOWED_SYMBOLS      = "EURUSD,XAUUSD"
$env:YUGEN_MT5_ALLOW_LIVE_TRADING   = "false"
$env:YUGEN_MT5_ALLOW_REAL_ACCOUNTS  = "false"

$env:YUGEN_MT5_REMOTE_ENABLED       = "true"
$env:YUGEN_MT5_REMOTE_HOST          = "0.0.0.0"              # bind público — nivel "public"
$env:YUGEN_MT5_REMOTE_PORT          = "8765"
$env:YUGEN_MT5_REMOTE_BEARER_TOKEN  = "<YOUR_TOKEN>"
$env:YUGEN_MT5_REMOTE_ALLOWLIST     = "<YOUR_PUBLIC_IP>/32"  # la IP de tu máquina personal
$env:YUGEN_MT5_REMOTE_ALLOW_INSECURE= "true"                 # reconoce el riesgo de no usar TLS

yugen-mt5-mcp run --transport remote --host 0.0.0.0 --port 8765
```

**5. Revisa la postura del servidor** (en una segunda ventana de PowerShell en el VPS):

```powershell
$env:YUGEN_MT5_REMOTE_ENABLED="true"; $env:YUGEN_MT5_REMOTE_HOST="0.0.0.0"
$env:YUGEN_MT5_REMOTE_ALLOW_INSECURE="true"; $env:YUGEN_MT5_REMOTE_BEARER_TOKEN="<YOUR_TOKEN>"
$env:YUGEN_MT5_REMOTE_ALLOWLIST="<YOUR_PUBLIC_IP>/32"; $env:YUGEN_MT5_ALLOWED_SYMBOLS="EURUSD,XAUUSD"
yugen-mt5-mcp doctor
```

Salida esperada: `remote_transport [WARN]` con `CRITICAL: "INSECURE: public bind without TLS
— token is transmitted in cleartext"`. Esto es correcto — el doctor está funcionando según lo diseñado.

Consulta [Verificación con doctor](#verificación-con-doctor) en el apéndice para el significado de cada severidad.

**6. Conecta el cliente** (desde tu máquina personal):

Genera el fragmento de configuración:

```bash
yugen-mt5-mcp config remote --host <ELASTIC_IP> --port 8765 --token <YOUR_TOKEN> --scheme http
```

Para Claude Code, agrega el servidor directamente:

```bash
claude mcp add --transport http yugen-mt5-remote \
  "http://<ELASTIC_IP>:8765/mcp/" \
  --header "Authorization: Bearer <YOUR_TOKEN>"
```

O agrégalo manualmente a la configuración de tu cliente:

```json
{
  "mcpServers": {
    "yugen-mt5-remote": {
      "url": "http://<ELASTIC_IP>:8765/mcp/",
      "headers": { "Authorization": "Bearer <YOUR_TOKEN>" }
    }
  }
}
```

Consulta [Verificación con curl](#verificación-con-curl) en el apéndice para probar la conectividad primero.

**7. Verifica y luego desmonta la Fase A:**

Pide al agente algo de solo lectura (p. ej. listar símbolos o ejecutar `doctor`). Una vez confirmado, apaga
la fase insegura inmediatamente:

```powershell
# Detén el servidor (Ctrl+C en su ventana), luego limpia:
Remove-NetFirewallRule -DisplayName "Yugen MCP 8765"
```

Elimina también la regla de entrada del puerto 8765 del Security Group de AWS.

### Fase B — TLS vía Caddy

**1. Crea un registro DNS A:** En tu proveedor de DNS, agrega un registro A que apunte
`mcp.yourdomain.com` a `ELASTIC_IP`. Espera la propagación (`nslookup mcp.yourdomain.com`).

**2. Actualiza el Security Group:** EC2 → `yugen-mt5-sg` → Inbound rules:

- Elimina la regla del puerto 8765 (ya no se expone directamente).
- Agrega: HTTP puerto `80` desde `0.0.0.0/0` — requerido para el desafío ACME de Let's Encrypt.
- Agrega: HTTPS puerto `443` desde `YOUR_PUBLIC_IP/32` — restringido solo a tu máquina.

**3. Abre los puertos 80 y 443 en Windows Defender Firewall** (PowerShell como Admin en el VPS).
Caddy puede crear estas reglas automáticamente; si no lo hace, agrégalas manualmente:

```powershell
New-NetFirewallRule -DisplayName "Caddy HTTP 80"  -Direction Inbound -Protocol TCP -LocalPort 80  -Action Allow
New-NetFirewallRule -DisplayName "Caddy HTTPS 443" -Direction Inbound -Protocol TCP -LocalPort 443 -Action Allow
```

Elimina estas reglas durante la limpieza, igual que eliminaste la regla del puerto 8765 en la Fase A.

**4. Instala Caddy en el VPS** (PowerShell como Admin):

```powershell
# Con winget (incluido en Windows Server 2022); o descarga el binario desde caddyserver.com/download
winget install CaddyServer.Caddy
```

Crea `C:\caddy\Caddyfile` usando el ejemplo de
[remote-transport.md — Caddyfile de ejemplo](remote-transport.md#caddyfile-de-ejemplo).

Inicia Caddy:

```powershell
caddy run --config C:\caddy\Caddyfile
```

Caddy obtiene y renueva el certificado de Let's Encrypt automáticamente. Déjalo corriendo en su
propia ventana, o regístralo como servicio de Windows para uso en producción.

**5. Inicia el servidor en modo seguro** (bind en loopback + TLS declarado):

```powershell
$env:YUGEN_MT5_ALLOWED_SYMBOLS      = "EURUSD,XAUUSD"
$env:YUGEN_MT5_ALLOW_LIVE_TRADING   = "false"
$env:YUGEN_MT5_ALLOW_REAL_ACCOUNTS  = "false"

$env:YUGEN_MT5_REMOTE_ENABLED       = "true"
$env:YUGEN_MT5_REMOTE_HOST          = "127.0.0.1"        # loopback — nivel trusted-local
$env:YUGEN_MT5_REMOTE_PORT          = "8765"
$env:YUGEN_MT5_REMOTE_BEARER_TOKEN  = "<YOUR_TOKEN>"
$env:YUGEN_MT5_REMOTE_TLS_TERMINATED= "true"             # declara que Caddy maneja TLS
$env:YUGEN_MT5_REMOTE_ALLOWLIST     = "<YOUR_PUBLIC_IP>/32"

yugen-mt5-mcp run --transport remote --host 127.0.0.1 --port 8765
```

> **Detalle de la lista blanca con XFF:** Cuando el servidor se enlaza a loopback, confía en el encabezado
> `X-Forwarded-For` que Caddy establece, y evalúa la lista blanca contra tu **IP pública real** — no
> `127.0.0.1`. Establece `YUGEN_MT5_REMOTE_ALLOWLIST` en `YOUR_PUBLIC_IP/32` (la IP de tu máquina
> personal). Si configuras `127.0.0.1/32` (como sugieren algunos ejemplos), toda solicitud será
> bloqueada con 403. Para la explicación conceptual de por qué funciona así, consulta
> [remote-transport.md — Modelo de niveles de confianza](remote-transport.md#modelo-de-niveles-de-confianza).

**6. Verifica la postura:**

```powershell
yugen-mt5-mcp doctor
```

Esperado: `remote_transport [OK]` — sin CRITICAL. A lo sumo una nota INFO sobre la lista blanca.

**7. Conecta el cliente** (desde tu máquina personal):

```bash
yugen-mt5-mcp config remote --host mcp.yourdomain.com --port 443 --token <YOUR_TOKEN>
```

O para Claude Code:

```bash
claude mcp add --transport http yugen-mt5-remote \
  "https://mcp.yourdomain.com/mcp/" \
  --header "Authorization: Bearer <YOUR_TOKEN>"
```

JSON de configuración del cliente:

```json
{
  "mcpServers": {
    "yugen-mt5-remote": {
      "url": "https://mcp.yourdomain.com/mcp/",
      "headers": { "Authorization": "Bearer <YOUR_TOKEN>" }
    }
  }
}
```

El puerto 443 es implícito — no lo incluyas en la URL. El token ahora viaja cifrado desde tu
máquina hasta Caddy.

### Endurecimiento para producción

- **Inyecta las variables de entorno mediante un servicio**, no de forma interactiva. Usa `--env-file .env` o registra el
  servidor y Caddy como servicios de Windows (p. ej. con NSSM). Mantén el archivo `.env` con permisos
  restringidos y nunca lo subas al repositorio.
- **No habilites el trading hasta haber probado en demo.** Deja `YUGEN_MT5_ALLOW_LIVE_TRADING`
  y `YUGEN_MT5_ALLOW_REAL_ACCOUNTS` en `false` hasta que tengas confianza en la configuración. Consulta
  [Escalamiento de seguridad](#escalamiento-de-seguridad) para la progresión paso a paso.
- **Restringe la lista blanca** al CIDR `/32` exacto de tu máquina personal y revisa periódicamente el
  log de auditoría SQLite (`YUGEN_MT5_AUDIT_PATH`).

### Limpieza (evitar costos continuos de AWS)

- Detén o termina la instancia EC2 cuando no esté en uso.
- **Libera la Elastic IP** si terminas la instancia — las Elastic IPs sin asociar se
  facturan por separado.
- Elimina el Security Group y el par de claves si no los vas a reutilizar.
- Elimina las reglas del Windows Firewall que creaste (puertos 80, 443 y 8765 si se ejecutó la Fase A).

---

## Escalamiento de seguridad

El servidor opera en tres niveles de permisos. Escala deliberadamente — no te saltes niveles.

| Nivel | Variables de entorno requeridas | Efecto |
|-------|--------------------------------|--------|
| **Solo lectura** (predeterminado) | ninguna | Datos de mercado, estado de la cuenta, información de posiciones; sin ejecución de órdenes |
| **Demo + trading en vivo** | `YUGEN_MT5_ALLOW_LIVE_TRADING=true` | Ejecución de órdenes habilitada; solo cuentas demo |
| **Cuenta real** | `YUGEN_MT5_ALLOW_REAL_ACCOUNTS=true` + llamar a la herramienta MCP `acknowledge_real_account` + `YUGEN_MT5_REAL_ACCOUNT_CONSENT` configurada | Operaciones en cuenta real permitidas; reconocimiento con alcance de sesión |

**Notas:**

- `YUGEN_MT5_REAL_ACCOUNT_CONSENT` se reinicia en cada reinicio del servidor. Cada nueva sesión requiere
  una llamada nueva a la herramienta MCP `acknowledge_real_account` antes de que procedan las operaciones en cuenta real.
- La herramienta `acknowledge_real_account` debe ser llamada por el cliente de IA al inicio de cada
  sesión donde se pretendan operaciones en cuenta real. Es una compuerta deliberada con alcance de sesión,
  no una configuración de una sola vez.
- La verificación `real_account_consent` del doctor reporta un WARNING cuando hay consentimiento ambiental activo
  (`YUGEN_MT5_REAL_ACCOUNT_CONSENT` configurada en el entorno) para mantener el riesgo visible.

Para la referencia completa de variables de entorno, consulta [Variables de entorno](#variables-de-entorno) en el apéndice.

---

## Apéndice de referencia

### Variables de entorno

Todas las variables `YUGEN_MT5_*` relevantes para conexión y seguridad.

- `REMOTE_*` y los booleanos de las compuertas de trading como `YUGEN_MT5_ALLOW_LIVE_TRADING` y
  `YUGEN_MT5_ALLOW_REAL_ACCOUNTS` se parsean como `true` / `false` (sin distinguir mayúsculas), donde
  solo `true` se trata como verdadero.
- `YUGEN_MT5_REAL_ACCOUNT_CONSENT` es diferente: acepta `1`, `true`, `yes` y `on`
  (sin distinguir mayúsculas) como valores verdaderos.

**Conexión y transporte**

Para la referencia canónica de variables `REMOTE_*` (`YUGEN_MT5_REMOTE_ENABLED`,
`YUGEN_MT5_REMOTE_HOST`, `YUGEN_MT5_REMOTE_PORT`, `YUGEN_MT5_REMOTE_BEARER_TOKEN`,
`YUGEN_MT5_REMOTE_TLS_TERMINATED`, `YUGEN_MT5_REMOTE_ALLOWLIST`,
`YUGEN_MT5_REMOTE_ALLOW_INSECURE`, `YUGEN_MT5_REMOTE_STATELESS_HTTP` y
`YUGEN_MT5_REMOTE_PATH`), consulta
[remote-transport.md — Variables de entorno](remote-transport.md#variables-de-entorno).
Todos los ejemplos de URL en esta guía asumen la ruta remota predeterminada `/mcp/`.

**Compuertas de seguridad y trading**

| Variable | Requerida | Predeterminado | Descripción |
|----------|-----------|----------------|-------------|
| `YUGEN_MT5_ALLOWED_SYMBOLS` | **Sí** | — | Lista blanca de símbolos separados por comas, o `*` para todos. El comodín imprime una advertencia al inicio pero no relaja ninguna compuerta de trading. |
| `YUGEN_MT5_ALLOW_LIVE_TRADING` | No | `false` | Establece `true` para habilitar la ejecución de órdenes. Cuando es `false`, el servidor es de solo lectura. |
| `YUGEN_MT5_ALLOW_REAL_ACCOUNTS` | No | `false` | Establece `true` para permitir operaciones en cuentas reales (no demo). |
| `YUGEN_MT5_REAL_ACCOUNT_CONSENT` | No | — | Token de consentimiento ambiental para operaciones en cuentas reales. Se reinicia en cada reinicio del servidor; establece pre-autorización ambiental. |
| `YUGEN_MT5_MAX_ORDER_VOLUME` | No | `1.0` | Volumen máximo en lotes por cada orden individual que crea exposición. Usa `unlimited` para deshabilitarlo (advertencia al inicio). |
| `YUGEN_MT5_MAX_SYMBOL_EXPOSURE` | No | `1.0` | Volumen abierto acumulado máximo por símbolo. Se verifica solo al abrir. Usa `unlimited` para deshabilitarlo (advertencia al inicio). |
| `YUGEN_MT5_AUDIT_PATH` | No | `var/audit.sqlite3` | Ruta de la base de datos SQLite de auditoría. **Usa una ruta absoluta con clientes de escritorio.** |

---

### Generación de tokens

Genera un token aleatorio criptográficamente fuerte antes de habilitar el transporte remoto.

**En Linux / macOS / WSL:**

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Alternativa usando OpenSSL:

```bash
openssl rand -hex 32
```

**En Windows (PowerShell):**

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Guarda el token en tu archivo `.env` o configúralo como variable de entorno. Nunca lo subas al
control de versiones.

---

### Verificación con doctor

Ejecuta la verificación de preparación integrada antes de conectar un cliente:

```powershell
yugen-mt5-mcp doctor
```

Para salida JSON (útil para scripting):

```powershell
yugen-mt5-mcp doctor --json
```

Interpreta `OK` como postura limpia, `WARN` cuando el servidor arranca igualmente con un riesgo revisable,
`CRITICAL` cuando la postura es insegura (por ejemplo la prueba HTTP pública intencional de la Fase A), y
`SKIPPED` cuando una verificación no aplica.

Para la referencia completa de comandos, el comportamiento de los códigos de salida y ejemplos detallados de postura
remota, consulta [cli.md — doctor](cli.md#doctor) y
[remote-transport.md — Verificación de postura del doctor](remote-transport.md#verificación-de-postura-del-doctor).

---

### Verificación con curl

Prueba la conectividad antes de configurar el cliente de IA:

```bash
# HTTP (loopback / LAN / Fase A)
curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer <YOUR_TOKEN>" \
  http://<HOST>:<PORT>/mcp/

# HTTPS (Fase B / producción)
curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer <YOUR_TOKEN>" \
  https://mcp.yourdomain.com/mcp/
```

Respuesta esperada: `200` o `405` (el servidor es alcanzable; `405` significa que el método GET no se
acepta en ese endpoint, lo cual es normal — MCP usa POST). Un `401` significa que el token es incorrecto.
Un timeout significa que falta una regla de firewall.

---

### Advertencia de AUDIT_PATH

La ruta de auditoría predeterminada es `var/audit.sqlite3` (relativa). Cuando un cliente de escritorio (Claude Desktop,
Cursor, OpenCode) lanza el servidor, establece el directorio de trabajo en el directorio de la propia
aplicación cliente — no en la raíz del proyecto. La ruta relativa entonces se resuelve en una ubicación
inesperada, y la base de datos puede no crearse donde esperas.

**Usa siempre una ruta absoluta para `YUGEN_MT5_AUDIT_PATH` en las configuraciones de clientes de escritorio:**

```
YUGEN_MT5_AUDIT_PATH=C:\Users\YOUR_USERNAME\AppData\Local\Yugen\mt5-mcp\audit.sqlite3
```

La ruta `yugen-mt5-mcp run --env-file` (Método 1) no se ve afectada porque tú controlas el
directorio de trabajo al lanzar desde una terminal. La advertencia de AUDIT_PATH en la salida del doctor
(`audit_path [WARN]`) aparecerá si la ruta no es escribible al inicio.
