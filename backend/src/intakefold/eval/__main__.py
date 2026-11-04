"""Run: python -m intakefold.eval --set development --database-url <empty eval database>"""

import argparse
import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

from intakefold.clock import SystemClock
from intakefold.db.engine import build_engine
from intakefold.db.seed import seed_vendors
from intakefold.documents.storage import Storage
from intakefold.eval.harness import (
    SETS,
    DatabaseNotEmpty,
    first_documents,
    load_labels,
    run_evaluation,
)
from intakefold.eval.report import write_reports
from intakefold.extraction.factory import build_extractor
from intakefold.settings import ConfigurationError, load_settings

ALEMBIC_INI = Path(__file__).parents[3] / "alembic.ini"


def parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score an extractor on the labeled set.")
    parser.add_argument("--set", choices=SETS, required=True, dest="set_name")
    parser.add_argument("--extractor", choices=("mock", "claude"), default="mock")
    parser.add_argument("--model", help="Claude model ID; defaults to CLAUDE_MODEL.")
    parser.add_argument(
        "--allow-real-model",
        action="store_true",
        help="Required with --extractor claude: real runs cost money and need the owner.",
    )
    parser.add_argument(
        "--database-url", required=True, help="An empty database, used for this run only."
    )
    parser.add_argument("--labels", type=Path, default=Path("../data/labeled"))
    parser.add_argument("--out", type=Path, default=Path("../reports/eval"))
    parser.add_argument("--token-cap", type=int, help="Defaults to BATCH_TOKEN_CAP.")
    parser.add_argument(
        "--limit",
        type=int,
        choices=range(1, 1000),
        metavar="N",
        help="Only the first N documents, for a smoke run. The report name says so.",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse()
    if arguments.extractor == "claude" and not arguments.allow_real_model:
        raise SystemExit("A real-model run needs --allow-real-model, and the owner's go-ahead.")
    overrides: dict[str, object] = {
        "database_url": arguments.database_url,
        "extractor": arguments.extractor,
        "labels_dir": arguments.labels,
    }
    if arguments.model:
        overrides["claude_model"] = arguments.model
    if arguments.token_cap:
        overrides["batch_token_cap"] = arguments.token_cap
    try:
        settings = load_settings(**overrides)
    except ConfigurationError as error:
        raise SystemExit(str(error)) from None

    config = Config(ALEMBIC_INI)
    config.attributes["database_url"] = arguments.database_url
    command.upgrade(config, "head")
    engine = build_engine(settings)
    with Session(engine) as session, session.begin():
        seed_vendors(session)
    labels, run_name = first_documents(
        load_labels(arguments.labels, arguments.set_name), arguments.set_name, arguments.limit
    )
    with tempfile.TemporaryDirectory() as directory:
        try:
            result = run_evaluation(
                engine,
                Storage(Path(directory)),
                SystemClock(),
                settings,
                build_extractor(settings, engine),
                labels,
                run_name,
            )
        except DatabaseNotEmpty:
            raise SystemExit(
                "That database already has documents. Uploads deduplicate by content, so an "
                "evaluation needs an empty database each time."
            ) from None
    engine.dispose()
    markdown, data = write_reports(result, arguments.out)
    print(f"Wrote {markdown} and {data}")


if __name__ == "__main__":
    main()
