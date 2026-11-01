"""Writes the labeled set. Run: python -m intakefold.generator --out ../data/labeled"""

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from intakefold.generator.labels import build_label
from intakefold.generator.layouts import draw_pdf
from intakefold.generator.plan import DEFAULT_SEED, DocumentPlan, plan_set
from intakefold.generator.scan import scan

EXTENSIONS = {"pdf": "pdf", "jpeg": "jpg", "png": "png"}
MEDIA_TYPES = {"pdf": "application/pdf", "jpeg": "image/jpeg", "png": "image/png"}


@dataclass(frozen=True)
class GeneratedDocument:
    plan: DocumentPlan
    pdf: bytes  # The page before any scan effects, for checking labels against what was drawn.
    content: bytes
    label: dict[str, object]


def generate(plan: DocumentPlan) -> GeneratedDocument:
    pdf = draw_pdf(plan)
    content = pdf if plan.file_format == "pdf" else scan(pdf, plan)
    label = build_label(plan) | {
        "file": f"{plan.id}.{EXTENSIONS[plan.file_format]}",
        "media_type": MEDIA_TYPES[plan.file_format],
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    return GeneratedDocument(plan, pdf, content, label)


def write_set(out: Path, seed: int) -> int:
    plans = plan_set(seed)
    for plan in plans:
        document = generate(plan)
        directory = out / plan.split
        directory.mkdir(parents=True, exist_ok=True)
        (directory / str(document.label["file"])).write_bytes(document.content)
        (directory / f"{plan.id}.json").write_text(
            json.dumps(document.label, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    return len(plans)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the fictional labeled set.")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    arguments = parser.parse_args()
    count = write_set(arguments.out, arguments.seed)
    print(f"Wrote {count} documents to {arguments.out}")


if __name__ == "__main__":
    main()
