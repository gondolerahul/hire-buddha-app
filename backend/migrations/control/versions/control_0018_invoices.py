"""GST invoices, credit notes, refunds (Phase 15 T6-5, T6-6)

Revision ID: control_0018_invoices
Revises: control_0017_plans
Create Date: 2026-10-24

* ``invoices`` / ``invoice_lines``: one tax invoice per payment received (TX-3),
  numbered from a gap-free series per financial year (``document_series``, TX-4).
* ``credit_notes`` against an invoice, and ``refunds`` (staff, T6-6).
* ``payment_transactions`` + ``purpose``, ``net_amount``, ``tax_amount``,
  ``gross_amount``, ``invoice_id``, ``refunded_gross``. Payments made before
  carried no GST: their net and gross are the amount, tax 0, and they have no
  invoice.
* The GST settings (``tax.*``, ``invoice.series_prefix``) are catalogue keys
  with defaults; staff set the supplier's GSTIN and address before the first
  invoice.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'control_0018_invoices'
down_revision: Union[str, Sequence[str], None] = 'control_0017_plans'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EXACT = sa.Numeric(precision=24, scale=10)
JSON_EMPTY = sa.text("'{}'::jsonb")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('document_series',
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('prefix', sa.String(length=20), nullable=False),
    sa.Column('financial_year', sa.String(length=7), nullable=False),
    sa.Column('next_number', sa.Integer(), server_default='1', nullable=False),
    sa.PrimaryKeyConstraint('kind', 'prefix', 'financial_year'),
    info={'plane': 'control'}
    )
    for name, column in (('purpose', sa.String(length=30)), ('net_amount', EXACT), ('tax_amount', EXACT),
                         ('gross_amount', EXACT), ('invoice_id', sa.UUID())):
        op.add_column('payment_transactions', sa.Column(name, column, nullable=True))
    op.add_column('payment_transactions', sa.Column('refunded_gross', EXACT, server_default='0', nullable=False))
    op.create_table('invoices',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('number', sa.String(length=40), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('payment_id', sa.UUID(), nullable=False),
    sa.Column('currency', sa.CHAR(length=3), nullable=False),
    sa.Column('net', EXACT, nullable=False),
    sa.Column('cgst', EXACT, server_default='0', nullable=False),
    sa.Column('sgst', EXACT, server_default='0', nullable=False),
    sa.Column('igst', EXACT, server_default='0', nullable=False),
    sa.Column('tax', EXACT, server_default='0', nullable=False),
    sa.Column('total', EXACT, nullable=False),
    sa.Column('tax_rate', sa.Numeric(precision=10, scale=4), nullable=False),
    sa.Column('regime', sa.String(length=20), nullable=False),
    sa.Column('place_of_supply', sa.String(length=10), nullable=True),
    sa.Column('customer', postgresql.JSONB(astext_type=sa.Text()), server_default=JSON_EMPTY, nullable=False),
    sa.Column('supplier', postgresql.JSONB(astext_type=sa.Text()), server_default=JSON_EMPTY, nullable=False),
    sa.Column('issued_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('pdf_key', sa.Text(), nullable=True),
    sa.Column('emailed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['payment_id'], ['payment_transactions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('number'),
    sa.UniqueConstraint('payment_id'),
    info={'plane': 'control'}
    )
    op.create_index('ix_invoices_company', 'invoices', ['company_id', 'issued_at'], unique=False)
    op.create_table('invoice_lines',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('invoice_id', sa.UUID(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('sac', sa.String(length=10), nullable=True),
    sa.Column('quantity', EXACT, server_default='1', nullable=False),
    sa.Column('amount', EXACT, nullable=False),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    info={'plane': 'control'}
    )
    op.create_index(op.f('ix_invoice_lines_invoice_id'), 'invoice_lines', ['invoice_id'], unique=False)
    op.create_table('credit_notes',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('number', sa.String(length=40), nullable=False),
    sa.Column('invoice_id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('currency', sa.CHAR(length=3), nullable=False),
    sa.Column('net', EXACT, nullable=False),
    sa.Column('cgst', EXACT, server_default='0', nullable=False),
    sa.Column('sgst', EXACT, server_default='0', nullable=False),
    sa.Column('igst', EXACT, server_default='0', nullable=False),
    sa.Column('tax', EXACT, server_default='0', nullable=False),
    sa.Column('total', EXACT, nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('issued_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('pdf_key', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('number'),
    info={'plane': 'control'}
    )
    op.create_index(op.f('ix_credit_notes_invoice_id'), 'credit_notes', ['invoice_id'], unique=False)
    op.create_table('refunds',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('payment_id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('currency', sa.CHAR(length=3), nullable=False),
    sa.Column('gross', EXACT, nullable=False),
    sa.Column('net', EXACT, nullable=False),
    sa.Column('credit_taken', EXACT, server_default='0', nullable=False),
    sa.Column('debt_added', EXACT, server_default='0', nullable=False),
    sa.Column('gateway_refund_id', sa.Text(), nullable=True),
    sa.Column('credit_note_id', sa.UUID(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['payment_id'], ['payment_transactions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    info={'plane': 'control'}
    )
    op.create_index(op.f('ix_refunds_payment_id'), 'refunds', ['payment_id'], unique=False)
    op.execute("""
        UPDATE payment_transactions SET
            purpose = CASE transaction_type WHEN 'subscription_charge' THEN 'subscription' ELSE transaction_type END,
            net_amount = amount, tax_amount = 0, gross_amount = amount
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_refunds_payment_id'), table_name='refunds')
    op.drop_table('refunds')
    op.drop_index(op.f('ix_credit_notes_invoice_id'), table_name='credit_notes')
    op.drop_table('credit_notes')
    op.drop_index(op.f('ix_invoice_lines_invoice_id'), table_name='invoice_lines')
    op.drop_table('invoice_lines')
    op.drop_index('ix_invoices_company', table_name='invoices')
    op.drop_table('invoices')
    for name in ('refunded_gross', 'invoice_id', 'gross_amount', 'tax_amount', 'net_amount', 'purpose'):
        op.drop_column('payment_transactions', name)
    op.drop_table('document_series')
