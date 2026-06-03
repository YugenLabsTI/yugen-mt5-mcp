"""Chart bridge end-to-end smoke test — drives the REAL ChartBridgeClient.

Validates the full Slice B path (pipe + HMAC + MQL5 ObjectCreate/Delete) WITHOUT
Claude Desktop or the MCP. It talks straight to the running MQL5 Service over the
named pipe, using the same object shapes the MCP tools emit.

Run order (on the Windows box running MT5):
    1. Open a chart in MT5 for the symbol you will pass below.
    2. Start the YugenChartBridgeService (Navigator > Services) with its
       SharedSecret input == the secret you export here.
    3. set YUGEN_MT5_CHART_SHARED_SECRET=<your-secret>
    4. python scripts/chart_smoke.py "EURUSD"
       (use whatever symbol has an open chart, e.g. "Boom 1000 Index")

Each step prints OK/FAIL. Watch the chart: a red SL line, a green TP line, and a
rectangle should appear, then the SL line should vanish, then everything yugen_*
should be cleared.
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


def main() -> int:
    secret = os.environ.get("YUGEN_MT5_CHART_SHARED_SECRET", "").strip()
    if not secret:
        print("ERROR: set YUGEN_MT5_CHART_SHARED_SECRET (must match the Service input).")
        return 1
    pipe_name = os.environ.get("YUGEN_MT5_CHART_PIPE_NAME", "yugen_chart_bridge").strip()
    symbol = sys.argv[1] if len(sys.argv) > 1 else "EURUSD"

    print(f"[smoke] pipe={pipe_name} symbol={symbol!r}")

    config = ChartBridgeConfig(pipe_name=pipe_name, shared_secret=secret, timeout_seconds=10.0)
    audit_path = Path(tempfile.gettempdir()) / "yugen_chart_smoke_audit.sqlite3"
    client = ChartBridgeClient(
        config=config,
        audit_store=AuditStore(audit_path),
        transport=PipeTransport(pipe_name=pipe_name),
    )
    chart = ChartSelector(symbol=symbol)

    # 1. Discover charts
    _step("list_charts", client.list_charts)

    # 2. Red SL horizontal line (mirrors draw_sl_line)
    _step(
        "create yugen_sl_smoke (red HLINE)",
        lambda: client.create_object(
            chart=chart,
            object_spec=ChartObjectSpec(
                name="yugen_sl_smoke",
                object_type="HLINE",
                properties={"color": "red", "style": "solid", "width": 1, "description": "SL"},
                points=(ChartObjectPoint(price=_nudge(symbol, below=True)),),
            ),
        ),
    )

    # 3. Green TP horizontal line (mirrors draw_tp_line)
    _step(
        "create yugen_tp_smoke (green HLINE)",
        lambda: client.create_object(
            chart=chart,
            object_spec=ChartObjectSpec(
                name="yugen_tp_smoke",
                object_type="HLINE",
                properties={"color": "green", "style": "solid", "width": 1, "description": "TP"},
                points=(ChartObjectPoint(price=_nudge(symbol, below=False)),),
            ),
        ),
    )

    # 4. Rectangle zone (mirrors draw_zone — price-only points)
    _step(
        "create yugen_zone_smoke (RECTANGLE)",
        lambda: client.create_object(
            chart=chart,
            object_spec=ChartObjectSpec(
                name="yugen_zone_smoke",
                object_type="RECTANGLE",
                properties={"color": "blue", "description": "smoke zone"},
                points=(
                    ChartObjectPoint(price=_nudge(symbol, below=True)),
                    ChartObjectPoint(price=_nudge(symbol, below=False)),
                ),
            ),
        ),
    )

    # 5. Delete just the SL line
    _step(
        "delete yugen_sl_smoke",
        lambda: client.delete_object(chart=chart, object_name="yugen_sl_smoke"),
    )

    # 6. Clear all yugen_* on this symbol
    _step("clear_objects (yugen_* on symbol)", lambda: client.clear_objects(symbol=symbol))

    print("\n[smoke] done. Check the MT5 chart + the Experts/Journal tab for details.")
    return 0


def _nudge(symbol: str, *, below: bool) -> float:
    """A placeholder price near a typical level.

    The smoke test only needs *some* price so the object is created; exact
    placement is not the point. Adjust if your symbol trades at a very
    different magnitude (e.g. an index in the thousands).
    """
    base = 10000.0 if "1000" in symbol or "Index" in symbol else 1.0
    return base * (0.99 if below else 1.01)


if __name__ == "__main__":
    raise SystemExit(main())
