"""remove default pricing: prices belong to a customer type or a customer

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-19

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # An item with no price for a customer is left unpriced; there is no
    # fallback, so the default prices (including the ones 0024 seeded) go.
    op.execute(
        "DELETE FROM item_prices WHERE customer_type_id IS NULL AND customer_id IS NULL;"
    )
    op.execute("ALTER TABLE item_prices DROP CONSTRAINT IF EXISTS ck_item_prices_one_scope;")
    op.execute(
        "ALTER TABLE item_prices ADD CONSTRAINT ck_item_prices_one_scope "
        "CHECK ((customer_type_id IS NULL) <> (customer_id IS NULL));"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE item_prices DROP CONSTRAINT IF EXISTS ck_item_prices_one_scope;")
    op.execute(
        "ALTER TABLE item_prices ADD CONSTRAINT ck_item_prices_one_scope "
        "CHECK (customer_type_id IS NULL OR customer_id IS NULL);"
    )
