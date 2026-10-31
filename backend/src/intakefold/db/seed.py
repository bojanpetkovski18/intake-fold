"""Fictional vendors and users. Safe to run repeatedly. Run: python -m intakefold.db.seed"""

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from intakefold.db.engine import build_engine
from intakefold.db.models import Role, User, Vendor, new_id
from intakefold.settings import load_settings

# M3 replaces this with real hashes. "!" can never match an argon2 hash, so nobody can sign in.
UNUSABLE_PASSWORD = "!"  # noqa: S105

VENDORS: list[tuple[str, str, list[str]]] = [
    ("Quillbrook Office Supply", "quillbrook office supply", ["Quillbrook"]),
    ("Tarnwell Freight", "tarnwell freight", ["Tarnwell Freight Co"]),
    ("Morrowfen Catering", "morrowfen catering", []),
    ("Ostrel Print Works", "ostrel print works", ["Ostrel Print"]),
]

USERS = [
    ("reviewer@example.com", "Riley Reviewer", Role.REVIEWER),
    ("admin@example.com", "Ada Admin", Role.ADMIN),
]


def seed(session: Session) -> None:
    for name, normalized_name, aliases in VENDORS:
        session.execute(
            insert(Vendor)
            .values(id=new_id(), name=name, normalized_name=normalized_name, aliases=aliases)
            .on_conflict_do_nothing(index_elements=[Vendor.normalized_name])
        )
    for email, display_name, role in USERS:
        session.execute(
            insert(User)
            .values(
                id=new_id(),
                email=email,
                display_name=display_name,
                role=role,
                password_hash=UNUSABLE_PASSWORD,
            )
            .on_conflict_do_nothing(index_elements=[User.email])
        )


def main() -> None:
    engine = build_engine(load_settings())
    with Session(engine) as session, session.begin():
        seed(session)
    engine.dispose()


if __name__ == "__main__":
    main()
