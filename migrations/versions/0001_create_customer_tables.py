"""create customer_types, customers, customer_contacts

Revision ID: 0001
Revises:
Create Date: 2026-08-12

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    op.create_table(
        "customer_types",
        sa.Column("customer_type_id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
    )

    op.create_table(
        "customers",
        sa.Column("customer_id", sa.Integer(), primary_key=True),
        sa.Column("customer_name", sa.String(length=255), nullable=False),
        sa.Column(
            "customer_type_id",
            sa.Integer(),
            sa.ForeignKey("customer_types.customer_type_id"),
            nullable=True,
        ),
        sa.Column(
            "parent_id", sa.Integer(), sa.ForeignKey("customers.customer_id"), nullable=True
        ),
        sa.Column("billing_address_line1", sa.String(length=255), nullable=True),
        sa.Column("billing_address_line2", sa.String(length=255), nullable=True),
        sa.Column("billing_city", sa.String(length=120), nullable=True),
        sa.Column("billing_state", sa.String(length=120), nullable=True),
        sa.Column("billing_postal_code", sa.String(length=20), nullable=True),
        sa.Column("billing_country", sa.String(length=120), nullable=True),
        sa.Column("shipping_address_line1", sa.String(length=255), nullable=True),
        sa.Column("shipping_address_line2", sa.String(length=255), nullable=True),
        sa.Column("shipping_city", sa.String(length=120), nullable=True),
        sa.Column("shipping_state", sa.String(length=120), nullable=True),
        sa.Column("shipping_postal_code", sa.String(length=20), nullable=True),
        sa.Column("shipping_country", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
    )
    op.create_index("ix_customers_customer_name", "customers", ["customer_name"])
    op.create_index("ix_customers_parent_id", "customers", ["parent_id"])

    op.create_table(
        "customer_contacts",
        sa.Column("contact_id", sa.Integer(), primary_key=True),
        sa.Column(
            "customer_id",
            sa.Integer(),
            sa.ForeignKey("customers.customer_id"),
            nullable=False,
        ),
        sa.Column("contact_name", sa.String(length=255), nullable=False),
        sa.Column("contact_phone", sa.String(length=50), nullable=True),
        sa.Column("contact_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
    )
    op.create_index("ix_customer_contacts_customer_id", "customer_contacts", ["customer_id"])

    for table in ("customer_types", "customers", "customer_contacts"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_set_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION set_updated_at();
            """
        )


def downgrade() -> None:
    for table in ("customer_contacts", "customers", "customer_types"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_set_updated_at ON {table};")

    op.drop_index("ix_customer_contacts_customer_id", table_name="customer_contacts")
    op.drop_table("customer_contacts")

    op.drop_index("ix_customers_parent_id", table_name="customers")
    op.drop_index("ix_customers_customer_name", table_name="customers")
    op.drop_table("customers")

    op.drop_table("customer_types")

    op.execute("DROP FUNCTION IF EXISTS set_updated_at();")
