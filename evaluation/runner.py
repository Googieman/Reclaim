"""Pure evaluation harness; it observes cases and cannot mutate business state."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from typing import Any

from .held_out_policy import FinalEvaluationAuthorization
from .report import build_report

EvaluationFunction = Callable[[Mapping[str, Any]], Mapping[str, Any]]


class EvaluationRunner:
    """Evaluate supplied records, retaining every case and its provenance."""

    def __init__(self, *, evaluator: EvaluationFunction | None = None) -> None:
        self.evaluator = evaluator

    def run(
        self,
        cases: Sequence[Mapping[str, Any]],
        *,
        provenance: Mapping[str, Any],
        evaluator: EvaluationFunction | None = None,
        held_out_authorization: FinalEvaluationAuthorization | None = None,
        seed: int | str = 0,
    ) -> dict[str, Any]:
        values = []
        selected_evaluator = evaluator or self.evaluator
        for case in cases:
            original = deepcopy(dict(case))
            if (
                str(original.get("split", "")) == "held_out"
                and held_out_authorization is None
            ):
                raise PermissionError(
                    "held-out evaluation requires final-evaluation authorization"
                )
            observed = (
                dict(selected_evaluator(original))
                if selected_evaluator is not None
                else {}
            )
            # Evaluation may add observations, but cannot replace identity or
            # provenance and cannot issue action commands.
            if any(
                key in observed
                for key in {"execute", "connector", "credentials", "database_write"}
            ):
                raise PermissionError(
                    "evaluation output cannot grant side-effect authority"
                )
            result = {**original, **observed}
            for key in (
                "evaluation_case_id",
                "tenant_id",
                "case_id",
                "provenance",
                "split",
            ):
                if key in original:
                    result[key] = original[key]
            values.append(result)
        report = build_report(values, provenance=provenance, seed=seed)
        report["evaluation_run_id"] = report["report_id"]
        report["case_results"] = tuple(values)
        report["failed_cases_visible"] = True
        report["side_effects"] = False
        return report


def run_evaluation(
    cases: Sequence[Mapping[str, Any]],
    *,
    provenance: Mapping[str, Any],
    evaluator: EvaluationFunction | None = None,
    held_out_authorization: FinalEvaluationAuthorization | None = None,
    seed: int | str = 0,
) -> dict[str, Any]:
    return EvaluationRunner(evaluator=evaluator).run(
        cases,
        provenance=provenance,
        held_out_authorization=held_out_authorization,
        seed=seed,
    )


evaluate = run_evaluation

__all__ = ["EvaluationRunner", "evaluate", "run_evaluation"]
