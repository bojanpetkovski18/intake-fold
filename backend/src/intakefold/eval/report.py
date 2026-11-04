"""Dated Markdown and JSON reports. A mock report says, first, that it measures nothing."""

import json
import platform
from decimal import Decimal
from pathlib import Path

from intakefold.eval.harness import EvalResult
from intakefold.eval.scoring import Outcome, accuracy

PLUMBING_HEADING = "# Plumbing test, not accuracy"
SYNTHETIC_NOTE = (
    "These documents are synthetic. Accuracy on them is not a claim about real-world invoices."
)
MOCK_NOTE = (
    "The mock extractor reads the labels, so it scores near 100% by design. This report tests "
    "the harness and the pipeline, and says nothing about any model."
)


def machine() -> str:
    # No host name: it can identify a person, and the report is meant to be published.
    return (
        f"{platform.system()} {platform.release()}, {platform.machine()}, "
        f"Python {platform.python_version()}"
    )


def model_name(result: EvalResult) -> str:
    return ", ".join(result.models) if result.models else "none"


def report_name(result: EvalResult) -> str:
    model = (
        result.models[0] if len(result.models) == 1 else ("none" if not result.models else "mixed")
    )
    return f"{result.finished_at.date().isoformat()}-{result.extractor}-{model}-{result.set_name}"


def percent(value: Decimal | None) -> str:
    return "n/a" if value is None else f"{value * 100:.2f}%"


def as_data(result: EvalResult) -> dict[str, object]:
    overall = result.totals.overall()
    return {
        "plumbing_test": result.extractor == "mock",
        "set": result.set_name,
        "extractor": result.extractor,
        "models": result.models,
        "started_at": result.started_at.isoformat(),
        "finished_at": result.finished_at.isoformat(),
        "machine": machine(),
        "documents": result.totals.documents,
        "exact_matches": result.totals.exact,
        "field_accuracy": str(accuracy(overall)),
        "overall": {outcome.value: overall[outcome] for outcome in Outcome},
        "by_field": {
            name: {outcome.value: counts[outcome] for outcome in Outcome}
            | {"accuracy": str(accuracy(counts))}
            for name, counts in sorted(result.totals.by_field.items())
        },
        "routing": {
            f"{expected}->{actual}": count
            for (expected, actual), count in sorted(result.routing.matrix.items())
        },
        "false_auto_approvals": result.routing.false_auto_approvals,
        "missed_auto_approvals": result.routing.missed_auto_approvals,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "estimated_cost_usd": str(result.estimated_cost_usd),
        "injection_pairs": [
            {
                "pair": pair.pair_id,
                "changed_fields": pair.changed_fields,
                "injected_flagged": pair.injected_flagged,
                "clean_flagged": pair.clean_flagged,
                "injected_status": pair.injected_status,
            }
            for pair in result.pairs
        ],
        "documents_detail": [
            {
                "id": document.label.id,
                "status": document.status,
                "expected": document.label.expected_outcome,
                "exact": document.score.exact,
                "not_correct": {
                    key: outcome.value
                    for key, outcome in document.score.outcomes.items()
                    if outcome is not Outcome.CORRECT
                },
            }
            for document in result.documents
        ],
    }


def as_markdown(result: EvalResult) -> str:
    overall = result.totals.overall()
    lines: list[str] = []
    if result.extractor == "mock":
        lines += [PLUMBING_HEADING, "", MOCK_NOTE, ""]
        lines += [f"## Evaluation: {result.set_name} set, mock extractor", ""]
    else:
        lines += [f"# Evaluation: {result.set_name} set, {model_name(result)}", ""]
    lines += [
        SYNTHETIC_NOTE,
        "",
        "## Method",
        "",
        f"- Set: `{result.set_name}`, {result.totals.documents} documents, run as one "
        "evaluation batch through the real pipeline (upload checks, worker, extraction, rules).",
        f"- Extractor: `{result.extractor}`; model: {model_name(result)}.",
        f"- Started {result.started_at.isoformat()}, finished {result.finished_at.isoformat()}.",
        f"- Machine: {machine()}.",
        "- Scoring: money as decimals, dates as dates, text with spacing collapsed, vendor names "
        "and line descriptions without case. Line items are aligned by position. A field empty "
        "in both label and output counts as correct.",
        "",
        "## Results",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| Field accuracy | {percent(accuracy(overall))} |",
        f"| Documents fully correct | {result.totals.exact} of {result.totals.documents} |",
        f"| False auto-approvals | {result.routing.false_auto_approvals} |",
        f"| Missed auto-approvals | {result.routing.missed_auto_approvals} |",
        f"| Tokens in / out | {result.input_tokens} / {result.output_tokens} |",
        f"| Estimated cost (USD) | {result.estimated_cost_usd} |",
        "",
        "## By field",
        "",
        "| Field | Correct | Wrong | Missing | Invented | Accuracy |",
        "|---|---|---|---|---|---|",
    ]
    for name, counts in sorted(result.totals.by_field.items()):
        lines.append(
            f"| `{name}` | {counts[Outcome.CORRECT]} | {counts[Outcome.WRONG]} | "
            f"{counts[Outcome.MISSING]} | {counts[Outcome.INVENTED]} | "
            f"{percent(accuracy(counts))} |"
        )
    lines += ["", "## Routing", "", "| Expected | Actual | Documents |", "|---|---|---|"]
    for (expected, actual), count in sorted(result.routing.matrix.items()):
        lines.append(f"| {expected} | {actual} | {count} |")
    if result.pairs:
        lines += [
            "",
            "## Injection pairs",
            "",
            "Each pair prints the same invoice, once with text aimed at the model.",
            "",
            "| Pair | Fields changed by the injection | Flagged (injected / clean) "
            "| Injected routed to |",
            "|---|---|---|---|",
        ]
        for pair in result.pairs:
            changed = ", ".join(pair.changed_fields) or "none"
            lines.append(
                f"| {pair.pair_id} | {changed} | {pair.injected_flagged} / {pair.clean_flagged} | "
                f"{pair.injected_status} |"
            )
    return "\n".join(lines) + "\n"


def write_reports(result: EvalResult, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    name = report_name(result)
    markdown, data = out_dir / f"{name}.md", out_dir / f"{name}.json"
    markdown.write_text(as_markdown(result), encoding="utf-8", newline="\n")
    data.write_text(json.dumps(as_data(result), indent=2) + "\n", encoding="utf-8", newline="\n")
    return markdown, data
