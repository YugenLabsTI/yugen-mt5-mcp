"""HMAC golden-vector unit tests — cross-language contract anchor.

# MQL5 QA: feed these vectors to HmacSha256Helper in the Service;
# hex output MUST match byte-for-byte.
#
# Vector 1:
#   secret="super-secret", schema_version="2026-05-31",
#   request_id="chart-abc123", action="create_object", idempotency_key="chart-abc123"
#   expected: "d4b80b74858ce0d87d6ccd9fbcf546686b2014b66b97d932f6fb2f8fe0513a36"
#
# Vector 2:
#   secret="x" * 80  (80 chars, forces K'=SHA256(K) branch), schema_version="2026-05-31",
#   request_id="chart-long-key", action="list_charts", idempotency_key="chart-long-key"
#   expected: "9aca2dab932142034bc63dbad5ab35ad0e87f1ee314f0b07c42932377e1b0abe"
#
# Vector 3:
#   secret="clé-secrète-€"  (multibyte UTF-8), schema_version="2026-05-31",
#   request_id="chart-utf8", action="delete_object", idempotency_key="idem-utf8"
#   expected: "c792b09aea5b65f0b035c09008f8c75201188171532880f8ce523f38936455b5"
"""

from __future__ import annotations

import hmac as _hmac
from hashlib import sha256

from yugen_mt5_mcp.chart_bridge import build_auth_tag

# ---------------------------------------------------------------------------
# Helper — compute expected value inline so these tests are self-contained
# ---------------------------------------------------------------------------

def _expected_tag(secret: str, schema_version: str, request_id: str, action: str, key: str) -> str:
    message = ":".join((schema_version, request_id, action, key)).encode("utf-8")
    digest = _hmac.new(secret.encode("utf-8"), message, sha256)
    return digest.hexdigest()


class TestHmacGoldenVectors:
    """Golden-vector assertions for build_auth_tag.

    Each vector asserts an exact hex string.  These strings are the
    authoritative cross-language contract — the MQL5 HmacSha256Helper
    on the Windows side MUST produce the same 64-char lowercase hex output.
    """

    def test_vector1_ascii_secret_and_message(self) -> None:
        """Vector 1 — ASCII secret, short message fields (standard case).

        MQL5 QA: feed these exact inputs to HmacSha256Helper and assert output
        equals "d4b80b74858ce0d87d6ccd9fbcf546686b2014b66b97d932f6fb2f8fe0513a36".
        """
        result = build_auth_tag(
            shared_secret="super-secret",
            schema_version="2026-05-31",
            request_id="chart-abc123",
            action="create_object",
            idempotency_key="chart-abc123",
        )
        expected = _expected_tag(
            "super-secret", "2026-05-31", "chart-abc123", "create_object", "chart-abc123"
        )
        assert len(result) == 64, "HMAC-SHA256 hex digest must be 64 characters"
        assert result == expected
        # Hardcoded to pin the value — this is the cross-language contract anchor.
        assert result == "d4b80b74858ce0d87d6ccd9fbcf546686b2014b66b97d932f6fb2f8fe0513a36"

    def test_vector2_secret_longer_than_64_bytes(self) -> None:
        """Vector 2 — secret longer than 64 bytes triggers K'=SHA256(K) branch in MQL5.

        MQL5 QA: secret is 80 'x' chars (forces K'=SHA256(K) pre-processing).
        HmacSha256Helper MUST print:
        "9aca2dab932142034bc63dbad5ab35ad0e87f1ee314f0b07c42932377e1b0abe"
        """
        long_secret = "x" * 80  # 80 bytes > 64-byte HMAC block size
        result = build_auth_tag(
            shared_secret=long_secret,
            schema_version="2026-05-31",
            request_id="chart-long-key",
            action="list_charts",
            idempotency_key="chart-long-key",
        )
        expected = _expected_tag(
            long_secret, "2026-05-31", "chart-long-key", "list_charts", "chart-long-key"
        )
        assert len(result) == 64
        assert result == expected
        # Hardcoded anchor — MQL5 side must reproduce this.
        assert result == "9aca2dab932142034bc63dbad5ab35ad0e87f1ee314f0b07c42932377e1b0abe"

    def test_vector3_multibyte_utf8_secret_and_message(self) -> None:
        """Vector 3 — multibyte UTF-8 secret + message locks the encoding path.

        MQL5 QA: secret contains non-ASCII chars (é, è, €).
        StringToCharArray with CP_UTF8 + drop trailing null MUST be used.
        HmacSha256Helper MUST print:
        "c792b09aea5b65f0b035c09008f8c75201188171532880f8ce523f38936455b5"
        """
        utf8_secret = "clé-secrète-€"  # multibyte: é=2 bytes, è=2 bytes, €=3 bytes
        result = build_auth_tag(
            shared_secret=utf8_secret,
            schema_version="2026-05-31",
            request_id="chart-utf8",
            action="delete_object",
            idempotency_key="idem-utf8",
        )
        expected = _expected_tag(
            utf8_secret, "2026-05-31", "chart-utf8", "delete_object", "idem-utf8"
        )
        assert len(result) == 64
        assert result == expected
        # Hardcoded anchor — MQL5 side must reproduce this.
        assert result == "c792b09aea5b65f0b035c09008f8c75201188171532880f8ce523f38936455b5"

    def test_build_auth_tag_is_deterministic(self) -> None:
        """build_auth_tag is pure — same inputs must always produce the same output."""
        kwargs = dict(
            shared_secret="secret",
            schema_version="2026-05-31",
            request_id="chart-xyz",
            action="update_object",
            idempotency_key="chart-xyz",
        )
        assert build_auth_tag(**kwargs) == build_auth_tag(**kwargs)
