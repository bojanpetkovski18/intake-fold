"""Fictional vendors and users. Safe to run repeatedly. Run: python -m intakefold.db.seed"""

from pydantic import SecretStr
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from intakefold.db.engine import build_engine
from intakefold.db.models import Role, User, Vendor, new_id
from intakefold.generator.vendors import KNOWN_VENDORS
from intakefold.identity.passwords import hash_password
from intakefold.settings import ConfigurationError, Settings, load_settings
from intakefold.validation.normalize import normalize_vendor

USERS = [
    ("reviewer@example.com", "Riley Reviewer", Role.REVIEWER),
    ("admin@example.com", "Ada Admin", Role.ADMIN),
]


def demo_passwords(settings: Settings) -> dict[Role, SecretStr]:
    reviewer, admin = settings.demo_reviewer_password, settings.demo_admin_password
    if reviewer is None or admin is None:
        raise ConfigurationError("Set DEMO_REVIEWER_PASSWORD and DEMO_ADMIN_PASSWORD to seed.")
    return {Role.REVIEWER: reviewer, Role.ADMIN: admin}


def seed(session: Session, passwords: dict[Role, SecretStr]) -> None:
    for vendor in KNOWN_VENDORS:
        session.execute(
            insert(Vendor)
            .values(
                id=new_id(),
                name=vendor.name,
                normalized_name=normalize_vendor(vendor.name),
                aliases=list(vendor.aliases),
            )
            .on_conflict_do_nothing(index_elements=[Vendor.normalized_name])
        )
    for email, display_name, role in USERS:
        password_hash = hash_password(passwords[role].get_secret_value())
        # Updates on conflict, so a changed password applies to an existing database.
        session.execute(
            insert(User)
            .values(
                id=new_id(),
                email=email,
                display_name=display_name,
                role=role,
                password_hash=password_hash,
            )
            .on_conflict_do_update(
                index_elements=[User.email], set_={"password_hash": password_hash}
            )
        )


def main() -> None:
    try:
        settings = load_settings()
        passwords = demo_passwords(settings)
    except ConfigurationError as error:
        raise SystemExit(str(error)) from None
    engine = build_engine(settings)
    with Session(engine) as session, session.begin():
        seed(session, passwords)
    engine.dispose()


if __name__ == "__main__":
    main()
