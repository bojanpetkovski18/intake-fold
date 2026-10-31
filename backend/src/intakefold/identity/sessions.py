import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta

import structlog
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from intakefold.clock import Clock
from intakefold.db.models import Role, User
from intakefold.db.models import Session as UserSession
from intakefold.identity.passwords import spend_verification_time, verify_password

log = structlog.get_logger()


@dataclass(frozen=True)
class Principal:
    session_id: uuid.UUID
    user_id: uuid.UUID
    email: str
    display_name: str
    role: Role
    csrf_token_hash: str


@dataclass(frozen=True)
class IssuedSession:
    token: str
    csrf_token: str
    principal: Principal


def hash_token(token: str) -> str:
    # SHA-256 is enough here: tokens are random, so there is nothing to guess offline.
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token_for(session_token: str) -> str:
    # Derived rather than random: /auth/me can return it again, while the database holds
    # only hashes, and every tab shares one token.
    return hmac.new(session_token.encode(), b"csrf", hashlib.sha256).hexdigest()


def csrf_token_matches(principal: Principal, candidate: str) -> bool:
    return hmac.compare_digest(hash_token(candidate), principal.csrf_token_hash)


def sign_in(
    engine: Engine, *, email: str, password: str, clock: Clock, ttl: timedelta
) -> IssuedSession | None:
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.email == email.strip().lower()))
        if user is None:
            spend_verification_time(password)
            log.warning("sign_in_failed")
            return None

    # Hashing is slow on purpose, so it stays outside any transaction.
    if not verify_password(user.password_hash, password):
        log.warning("sign_in_failed", user_id=str(user.id))
        return None

    token = secrets.token_urlsafe(32)
    csrf_token = csrf_token_for(token)
    now = clock.now()
    row = UserSession(
        token_hash=hash_token(token),
        csrf_token_hash=hash_token(csrf_token),
        user_id=user.id,
        expires_at=now + ttl,
    )
    with Session(engine) as session, session.begin():
        session.execute(delete(UserSession).where(UserSession.expires_at <= now))
        session.add(row)
        session.flush()
        principal = Principal(
            session_id=row.id,
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
            role=user.role,
            csrf_token_hash=row.csrf_token_hash,
        )
    log.info("sign_in_succeeded", user_id=str(user.id))
    return IssuedSession(token=token, csrf_token=csrf_token, principal=principal)


def authenticate(engine: Engine, token: str, clock: Clock) -> Principal | None:
    with Session(engine) as session:
        row = session.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(UserSession.token_hash == hash_token(token))
            .where(UserSession.expires_at > clock.now())
        ).one_or_none()
        if row is None:
            return None
        user_session, user = row
        return Principal(
            session_id=user_session.id,
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
            role=user.role,
            csrf_token_hash=user_session.csrf_token_hash,
        )


def sign_out(engine: Engine, principal: Principal) -> None:
    with Session(engine) as session, session.begin():
        session.execute(delete(UserSession).where(UserSession.id == principal.session_id))
    log.info("signed_out", user_id=str(principal.user_id))
