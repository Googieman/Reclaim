"""Conservative specialist promotion gates."""

from training.reclaim.scripts.evaluate import compare_reports


def report(recall: float, preservation: float) -> dict[str, object]:
    return {
        "status": "complete",
        "metrics": {
            "malicious_recall": recall,
            "legitimate_preservation": preservation,
            "forbidden_proposal_rate": 0.0,
            "prompt_injection_failure_rate": 0.0,
            "schema_valid_rate": 1.0,
        },
        "limitations": [],
    }


def test_promotion_rejects_specialist_regression() -> None:
    decision = compare_reports(report(0.8, 1.0), report(0.7, 1.0))
    assert decision["decision"] == "DON'T SHIP"


def test_promotion_accepts_non_regression_only_when_both_are_observed() -> None:
    decision = compare_reports(report(0.8, 1.0), report(0.8, 1.0))
    assert decision["decision"] == "SHIP"
