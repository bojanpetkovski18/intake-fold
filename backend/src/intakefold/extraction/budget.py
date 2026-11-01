import uuid
from decimal import Decimal

from sqlalchemy import Engine, update

from intakefold.db.models import Batch


class TokenBudget:
    """Reserves before a call, so concurrent workers can never pass a batch's cap together."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def reserve(self, batch_id: uuid.UUID, tokens: int) -> bool:
        # One statement, so the check and the increase cannot be separated by another worker.
        statement = (
            update(Batch)
            .where(Batch.id == batch_id, Batch.tokens_used + tokens <= Batch.token_cap)
            .values(tokens_used=Batch.tokens_used + tokens)
            .returning(Batch.id)
        )
        with self.engine.begin() as connection:
            return connection.execute(statement).first() is not None

    def settle(self, batch_id: uuid.UUID, reserved: int, used: int, cost: Decimal) -> None:
        """Replaces the reservation with what the call actually used."""
        statement = (
            update(Batch)
            .where(Batch.id == batch_id)
            .values(
                tokens_used=Batch.tokens_used - reserved + used,
                estimated_cost_usd=Batch.estimated_cost_usd + cost,
            )
        )
        with self.engine.begin() as connection:
            connection.execute(statement)
