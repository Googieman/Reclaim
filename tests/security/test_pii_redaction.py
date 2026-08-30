"""PII and secret redaction tests."""

from app.observability.redaction import redact


def test_redaction_removes_nested_pii_and_secrets_without_losing_ids() -> None:
    value = redact(
        {
            "tenant_id": "tenant-a",
            "case_id": "case-1",
            "customer": {"full_name": "A Person", "phone": "+1-555-0100"},
            "credentials": {"client_secret": "secret", "api_key": "key"},
        }
    )

    assert value["tenant_id"] == "tenant-a"
    assert value["case_id"] == "case-1"
    assert value["customer"]["full_name"] == "[REDACTED]"
    assert value["credentials"]["client_secret"] == "[REDACTED]"
