# Guía de despliegue del transporte remoto

> 🌐 **Idioma**: Español | [English](../remote-transport.md) · [Volver al índice](../index.md)

Esta guía cubre el despliegue de yugen-mt5-mcp en modo `remote`, donde un cliente en una
máquina o frontera de red diferente se conecta al servidor por HTTP con
autenticación de token bearer.

## Orientación rápida

```
Cliente
  -> [Terminador TLS: Caddy / nginx / LB en la nube / Cloudflare Tunnel]
  -> HTTP en loopback/privado  ->  yugen-mt5-mcp (uvicorn)
                                        -> Terminal MT5
```

TLS es responsabilidad del despliegue. yugen-mt5-mcp es agnóstico a TLS — funciona
cualquier proxy o servicio en la nube que termine HTTPS y reenvíe HTTP en texto plano al
proceso. Caddy es el ejemplo recomendado porque gestiona la renovación de certificados
automáticamente.

## Variables de entorno

| Variable | Tipo | Predeterminado | Descripción |
|---|---|---|---|
| `YUGEN_MT5_REMOTE_ENABLED` | bool (`true`/`false`) | `false` | Cambia de stdio a transporte HTTP |
| `YUGEN_MT5_REMOTE_HOST` | string | `127.0.0.1` | Dirección de enlace del listener HTTP |
| `YUGEN_MT5_REMOTE_PORT` | int 1–65535 | `8765` | Puerto del listener HTTP |
| `YUGEN_MT5_REMOTE_PATH` | string | `/mcp/` | Ruta HTTP servida por el transporte remoto |
| `YUGEN_MT5_REMOTE_BEARER_TOKEN` | string | requerido si está habilitado | Token secreto — los clientes deben enviar `Authorization: Bearer <token>` |
| `YUGEN_MT5_REMOTE_TLS_TERMINATED` | bool | `false` | Establece `true` cuando un proxy upstream maneja TLS (solo declaración, no se verifica por solicitud) |
| `YUGEN_MT5_REMOTE_ALLOWLIST` | CIDRs separados por comas o `*` | loopback + RFC 1918 | Lista blanca de IPs para conexiones entrantes; `*` significa permitir cualquier IP |
| `YUGEN_MT5_REMOTE_ALLOW_INSECURE` | bool | `false` | Excluye el requisito de TLS para binds públicos (riesgo asumido — ver abajo) |
| `YUGEN_MT5_REMOTE_STATELESS_HTTP` | bool | `false` | Usa el modo HTTP sin estado (sin sesión en el servidor; cambia eficiencia por proxying más simple) |

Todas las variables booleanas usan `true` / `false` (sin distinguir mayúsculas; `true` es el único
valor verdadero — cualquier otra cadena, incluyendo `1` o `yes`, se trata como `false`).

## Modelo de niveles de confianza

El servidor deriva un **nivel de confianza** (trust tier) a partir de la dirección de enlace:

| Nivel | Condición | Requisito de TLS |
|---|---|---|
| **trusted-local** | El bind es loopback (`127.x`, `::1`) o privado RFC 1918 (`10.x`, `172.16–31.x`, `192.168.x`) | TLS opcional — el token por sí solo es suficiente |
| **public** | Cualquier otra dirección, incluyendo `0.0.0.0` | TLS requerido (`YUGEN_MT5_REMOTE_TLS_TERMINATED=true`) salvo que `YUGEN_MT5_REMOTE_ALLOW_INSECURE=true` |

El bind predeterminado es `127.0.0.1` (loopback, trusted-local), así que habilitarlo
solo con un token bearer es seguro sin configurar TLS.

### Lista blanca predeterminada

Cuando `YUGEN_MT5_REMOTE_ALLOWLIST` no está configurada, el servidor acepta por defecto
conexiones desde loopback y rangos privados RFC 1918:

```
127.0.0.1/32, ::1/128, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
```

Es un valor predeterminado seguro para despliegues trusted-local. En producción, restríngela
a los CIDR específicos que controlas.

## Despliegue recomendado: Caddy (VPS público)

Caddy gestiona los certificados HTTPS automáticamente vía ACME y reenvía HTTP en texto plano
al listener de loopback. Esta es la ruta recomendada para un VPS público.

### Caddyfile de ejemplo

```caddyfile
# Reemplaza mcp.example.com con tu dominio real.
# Caddy obtiene y renueva un certificado de Let's Encrypt automáticamente.
mcp.example.com {
    reverse_proxy 127.0.0.1:8765
}
```

### Configuración del servidor

```bash
# En el VPS — bind en loopback para que solo Caddy (en el mismo host) pueda alcanzar el puerto.
export YUGEN_MT5_REMOTE_ENABLED=true
export YUGEN_MT5_REMOTE_HOST=127.0.0.1
export YUGEN_MT5_REMOTE_PORT=8765
export YUGEN_MT5_REMOTE_BEARER_TOKEN=<strong-random-secret>
export YUGEN_MT5_REMOTE_TLS_TERMINATED=true
# Lista blanca: acepta conexiones solo desde 127.0.0.1 (Caddy está en el mismo host).
export YUGEN_MT5_REMOTE_ALLOWLIST=127.0.0.1/32

python -m yugen_mt5_mcp
```

El cliente se conecta a `https://mcp.example.com/mcp/` con el token bearer en el
encabezado `Authorization`. Caddy reenvía la solicitud por loopback a
yugen-mt5-mcp, que ve el peer del socket como `127.0.0.1` y confía en el encabezado
`X-Forwarded-For` que Caddy establece. El servidor aplica el token y la
lista blanca antes de cualquier procesamiento MCP.

## Proveedores de TLS alternativos

Funciona cualquier terminador TLS que haga proxy de HTTP en texto plano hacia la dirección de enlace.
Establece `YUGEN_MT5_REMOTE_TLS_TERMINATED=true` para declarar que TLS se maneja
upstream (esto satisface el requisito de seguridad del bind público).

El campo `reverse_proxy` de la configuración es metadato informativo — no
cambia el comportamiento del servidor.

**nginx (con certbot)**

```nginx
server {
    listen 443 ssl;
    server_name mcp.example.com;
    ssl_certificate     /etc/letsencrypt/live/mcp.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mcp.example.com/privkey.pem;

    location / {
        proxy_pass         http://127.0.0.1:8765;
        proxy_set_header   X-Forwarded-For $remote_addr;
        proxy_set_header   Host $host;
    }
}
```

**Load balancer en la nube / Cloudflare Tunnel**

Apunta el load balancer o el túnel a `127.0.0.1:8765`. Establece
`YUGEN_MT5_REMOTE_TLS_TERMINATED=true`. El borde de la nube maneja el certificado;
el proceso MCP nunca ve TLS crudo.

## Válvula de escape ALLOW_INSECURE

`YUGEN_MT5_REMOTE_ALLOW_INSECURE=true` deshabilita el requisito de TLS para binds
públicos. Úsalo solo en entornos controlados donde la ruta de red entre
cliente y servidor ya está asegurada por otros medios (p. ej., una VPN o una red privada
en la nube sin ingreso público).

**Riesgo**: con `ALLOW_INSECURE` activo, el token bearer se transmite en
texto claro por la red. Cualquiera que pueda observar el tráfico puede capturar el
token y suplantar a un cliente legítimo. La verificación de postura del doctor lo reporta
como CRITICAL para mantener el riesgo visible.

## Interoperabilidad WSL / Windows

El modo de red NAT predeterminado de WSL implica que el guest de WSL no puede alcanzar el host
Windows vía `127.0.0.1` — están en espacios de nombres de loopback separados.

Dos opciones:

### Opción A — Red espejada de WSL (recomendada)

Habilita la red espejada (mirrored) en `.wslconfig` (Windows 11 22H2+):

```ini
[wsl2]
networkingMode=mirrored
```

Con la red espejada, `127.0.0.1` se comparte entre Windows y WSL. El
servidor se queda en su loopback predeterminado y el cliente en WSL lo alcanza directamente.
No se necesita cambiar la lista blanca.

### Opción B — bind a la IP privada de la LAN de WSL (modo NAT)

Encuentra la dirección del host Windows desde dentro de WSL:

```bash
cat /etc/resolv.conf | grep nameserver | awk '{print $2}'
# p. ej., 172.20.0.1
```

Enlaza el servidor a esa dirección:

```bash
export YUGEN_MT5_REMOTE_HOST=172.20.0.1   # la IP LAN del host Windows desde la perspectiva de WSL
export YUGEN_MT5_REMOTE_ALLOWLIST=172.16.0.0/12   # cubre la subred NAT de WSL
export YUGEN_MT5_REMOTE_BEARER_TOKEN=<secret>
# No se necesita TLS_TERMINATED — 172.20.0.1 es una dirección privada RFC 1918 (nivel trusted-local).
```

`172.16.0.0/12` cubre el rango completo RFC 1918 de clase B que asigna el NAT de WSL.
Restríngelo al `/32` específico si sabes que la dirección es estable.

## Verificación de postura del doctor

Ejecuta el doctor integrado para verificar la postura antes de desplegar:

```bash
# La verificación del doctor se invoca a través de la herramienta MCP doctor.
# Reporta trust_tier, tls_terminated, allowlist_entries y cualquier advertencia.
```

El doctor emite:

| Condición | Severidad | Mensaje |
|---|---|---|
| Bind público, ALLOW_INSECURE activo | CRITICAL | "INSECURE: public bind without TLS — token is transmitted in cleartext" |
| Bind público, TLS, lista blanca comodín (`*`) | WARNING | "allowlist is open (*) — any IP may attempt connection; token is the only gate" |
| Bind trusted-local, lista blanca comodín | INFO | "allowlist is open (*) on trusted-local bind — consider restricting to known CIDRs" |
| Todas las demás configuraciones | (sin advertencia) | Postura limpia |

El valor del token bearer nunca se emite en la salida del doctor.

## Resumen de seguridad

| Capa | Mecanismo |
|---|---|
| Cifrado de transporte | Terminador TLS (Caddy, nginx, LB en la nube, Cloudflare Tunnel) — no dentro del proceso |
| Autenticación | Token bearer verificado con `secrets.compare_digest` en cada solicitud |
| Autorización | IP del cliente verificada contra la lista blanca CIDR antes de validar el token |
| Confianza en XFF | Solo se confía cuando el peer del socket es loopback/privado (el terminador está coubicado) |
| Auditoría | Cada solicitud autorizada y bloqueada se agrega al log de auditoría SQLite con el token redactado |
| Postura predeterminada | Bind en loopback, lista blanca loopback+RFC 1918, TLS opcional para trusted-local |
