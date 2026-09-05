"""Unit coverage for the narrative-free, cursor-paginated case inbox."""

from datetime import UTC, datetime

import pytest
from app.cases.inbox import CaseInboxError, decode_cursor, encode_cursor


def test_case_inbox_cursor_round_trips_the_stable_sort_key() -> None:
    updated_at = datetime(2026, 9, 3, 9, 0, 1, tzinfo=UTC)
    cursor = encode_cursor(updated_at, "case-001")

    decoded_at, decoded_case_id = decode_cursor(cursor)

    assert decoded_at == updated_at
    assert decoded_case_id == "case-001"


@pytest.mark.parametrize("cursor", ["", "not-json", "e30", "eyJjYXNlX2lkIjoiY2FzZSJ9"])
def test_case_inbox_rejects_malformed_cursor(cursor: str) -> None:
    with pytest.raises(CaseInboxError, match="cursor is invalid"):
        decode_cursor(cursor)


def test_case_inbox_cursor_normalizes_to_utc() -> None:
    cursor = encode_cursor(datetime(2026, 9, 3, tzinfo=UTC), "case-001")
    assert decode_cursor(cursor)[0].tzinfo is UTC
