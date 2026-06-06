"""Chart bridge end-to-end smoke test — drives the REAL ChartBridgeClient.

Validates the full Slice B path (pipe + HMAC + MQL5 ObjectCreate/Delete) WITHOUT
Claude Desktop or the MCP. Talks straight to the running MQL5 Service over the
named pipe, using the same object shapes the MCP tools emit.

Usage (on the Windows box running MT5, with the Service started):
    set YUGEN_MT5_CHART_SHARED_SECRET=<secret matching the Service input>

    # 1. Just list the open charts:
    python scripts/chart_smoke.py "Boom 1000 Index"

    # 2. DRAW around the current price (read it off your chart) and LEAVE the
    #    objects on the chart so you can see them:
    python scripts/chart_smoke.py "Boom 1000 Index" 15000

    # 3. Clean up afterwards (remove every yugen_* object on that symbol):
    python scripts/chart_smoke.py "Boom 1000 Index" clear

Pass a price NEAR the current market level so the lines land on-screen.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from yugen_mt5_mcp.audit import AuditStore
from yugen_mt5_mcp.chart_bridge import (
    ChartBridgeClient,
    ChartBridgeConfig,
    ChartBridgeError,
    ChartObjectPoint,
    ChartObjectSpec,
    ChartSelector,
)
from yugen_mt5_mcp.pipe_transport import PipeTransport


def _step(label: str, fn: object) -> None:
    """Run one named step, printing OK + result or FAIL + error."""
    print(f"\n--- {label} ---")
    try:
        result = fn()  # type: ignore[operator]
    except ChartBridgeError as error:
        print(f"FAIL: {type(error).__name__}: {error}")
    except Exception as error:  # noqa: BLE001 - smoke test surfaces everything
        print(f"FAIL (unexpected): {type(error).__name__}: {error}")
    else:
        print(f"OK: {result}")


def _build_client() -> ChartBridgeClient:
    secret = os.environ.get("YUGEN_MT5_CHART_SHARED_SECRET", "").strip()
    if not secret:
        raise SystemExit("ERROR: set YUGEN_MT5_CHART_SHARED_SECRET (must match the Service input).")
    pipe_name = os.environ.get("YUGEN_MT5_CHART_PIPE_NAME", "yugen_chart_bridge").strip()
    audit_path = Path(tempfile.gettempdir()) / "yugen_chart_smoke_audit.sqlite3"
    return ChartBridgeClient(
        config=ChartBridgeConfig(pipe_name=pipe_name, shared_secret=secret, timeout_seconds=10.0),
        audit_store=AuditStore(audit_path),
        transport=PipeTransport(pipe_name=pipe_name),
    )


def main() -> int:
    symbol = sys.argv[1] if len(sys.argv) > 1 else "EURUSD"
    arg2 = sys.argv[2] if len(sys.argv) > 2 else None

    client = _build_client()
    chart = ChartSelector(symbol=symbol)

    # Always show the open charts first (also proves list_charts works).
    _step("list_charts", client.list_charts)

    if arg2 is None:
        print(
            f"\n[smoke] No price given. To DRAW visible objects, read the current "
            f"{symbol} price off your chart and run:\n"
            f'    python scripts/chart_smoke.py "{symbol}" <price>\n'
            f'    python scripts/chart_smoke.py "{symbol}" clear   # to remove them later'
        )
        return 0

    if arg2.lower() == "clear":
        _step(
            "clear_objects (remove all yugen_* on symbol)",
            lambda: client.clear_objects(symbol=symbol),
        )
        return 0

    try:
        price = float(arg2)
    except ValueError:
        print(f"ERROR: second arg must be a price number or 'clear', got {arg2!r}")
        return 1

    # Place objects close to the given price so they land on-screen.
    sl = round(price * 0.998, 5)
    tp = round(price * 1.002, 5)
    low = round(price * 0.997, 5)
    high = round(price * 1.003, 5)
    print(f"\n[smoke] drawing around {price}: SL={sl} TP={tp} zone=[{low}, {high}]")

    _step(
        "draw yugen_sl_smoke (red HLINE)",
        lambda: client.create_object(
            chart=chart,
            object_spec=ChartObjectSpec(
                name="yugen_sl_smoke",
                object_type="HLINE",
                properties={"color": "red", "style": "solid", "width": 2, "description": "SL"},
                points=(ChartObjectPoint(price=sl),),
            ),
        ),
    )
    _step(
        "draw yugen_tp_smoke (green HLINE)",
        lambda: client.create_object(
            chart=chart,
            object_spec=ChartObjectSpec(
                name="yugen_tp_smoke",
                object_type="HLINE",
                properties={"color": "green", "style": "solid", "width": 2, "description": "TP"},
                points=(ChartObjectPoint(price=tp),),
            ),
        ),
    )
    _step(
        "draw yugen_zone_smoke (RECTANGLE)",
        lambda: client.create_object(
            chart=chart,
            object_spec=ChartObjectSpec(
                name="yugen_zone_smoke",
                object_type="RECTANGLE",
                properties={"color": "blue", "description": "smoke zone"},
                points=(ChartObjectPoint(price=low), ChartObjectPoint(price=high)),
            ),
        ),
    )

    print(
        f"\n[smoke] done — objects LEFT on the chart. Look at your {symbol} chart now:\n"
        f"  red SL ~{sl}, green TP ~{tp}, blue zone between {low} and {high}.\n"
        f'  Remove them with: python scripts/chart_smoke.py "{symbol}" clear'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
