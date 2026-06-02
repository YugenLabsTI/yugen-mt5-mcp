"""Unit tests for to_payload serializer — WU1 (TDD red-first)."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from yugen_mt5_mcp.market_data import to_payload

# ---------------------------------------------------------------------------
# WU1-T1: Decimal → str
# ---------------------------------------------------------------------------


def test_to_payload_converts_decimal_to_string() -> None:
    value = Decimal("1.23456")
    result = to_payload(value)
    assert result == "1.23456"
    assert isinstance(result, str)


def test_to_payload_converts_decimal_nested_in_dict() -> None:
    result = to_payload({"volume": Decimal("0.10")})
    assert result == {"volume": "0.10"}


# ---------------------------------------------------------------------------
# WU1-T2: StrEnum → .value string
# ---------------------------------------------------------------------------


class _Colour(StrEnum):
    RED = "red"
    BLUE = "blue"


def test_to_payload_converts_strenum_to_value_string() -> None:
    result = to_payload(_Colour.RED)
    assert result == "red"
    assert isinstance(result, str)


def test_to_payload_converts_strenum_nested_in_dict() -> None:
    result = to_payload({"colour": _Colour.BLUE})
    assert result == {"colour": "blue"}


# ---------------------------------------------------------------------------
# Additive guard: existing scalar types must not regress
# ---------------------------------------------------------------------------


def test_to_payload_passthrough_int() -> None:
    assert to_payload(42) == 42


def test_to_payload_passthrough_float() -> None:
    assert to_payload(1.5) == 1.5


def test_to_payload_passthrough_str() -> None:
    assert to_payload("hello") == "hello"


def test_to_payload_passthrough_none() -> None:
    assert to_payload(None) is None
