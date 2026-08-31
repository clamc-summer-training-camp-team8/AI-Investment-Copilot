"""Persist frozen market data, research signals, and portfolio backtests."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0016_quant_productization"
down_revision = "0015_data_asset_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quant_market_dataset",
        sa.Column("dataset_id", sa.String(96), primary_key=True),
        sa.Column("data_version", sa.String(96), nullable=False, unique=True),
        sa.Column("manifest_path", sa.String(1024), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("source_policy_id", sa.String(96), nullable=False),
        sa.Column("authorization_status", sa.String(32), nullable=False),
        sa.Column("adjustment", sa.String(16), nullable=False),
        sa.Column("coverage_start", sa.Date(), nullable=False),
        sa.Column("coverage_end", sa.Date(), nullable=False),
        sa.Column("securities", postgresql.JSONB(), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(), nullable=False),
        sa.Column("limitations", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("frozen_by", sa.String(64), nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status = 'frozen'", name="ck_quant_market_dataset_quant_market_dataset_frozen"),
        sa.CheckConstraint("coverage_end >= coverage_start", name="ck_quant_market_dataset_quant_market_dataset_coverage"),
    )
    op.create_table(
        "quant_signal_set",
        sa.Column("signal_set_id", sa.String(96), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("version", sa.String(96), nullable=False, unique=True),
        sa.Column("content_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("signals", postgresql.JSONB(), nullable=False),
        sa.Column("signal_count", sa.Integer(), nullable=False),
        sa.Column("human_confirmed_only", sa.Boolean(), nullable=False),
        sa.Column("evaluation_track", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("frozen_by", sa.String(64), nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status = 'frozen'", name="ck_quant_signal_set_quant_signal_set_frozen"),
        sa.CheckConstraint("human_confirmed_only", name="ck_quant_signal_set_quant_signal_set_human_confirmed"),
        sa.CheckConstraint("evaluation_track = 'alpha_validation'", name="ck_quant_signal_set_quant_signal_set_alpha_track"),
        sa.CheckConstraint("signal_count > 0", name="ck_quant_signal_set_quant_signal_set_nonempty"),
    )
    op.create_table(
        "quant_backtest_run",
        sa.Column("run_id", sa.String(96), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("market_dataset_id", sa.String(96), sa.ForeignKey("quant_market_dataset.dataset_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("signal_set_id", sa.String(96), sa.ForeignKey("quant_signal_set.signal_set_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("methodology_version", sa.String(64), nullable=False),
        sa.Column("parameters", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.Column("evaluation_track", sa.String(32), nullable=False),
        sa.Column("requested_by", sa.String(64), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text()),
        sa.CheckConstraint("evaluation_track = 'alpha_validation'", name="ck_quant_backtest_run_quant_backtest_alpha_track"),
    )
    op.create_index("ix_quant_backtest_owner_time", "quant_backtest_run", ["requested_by", "generated_at"])


def downgrade() -> None:
    op.drop_index("ix_quant_backtest_owner_time", table_name="quant_backtest_run")
    op.drop_table("quant_backtest_run")
    op.drop_table("quant_signal_set")
    op.drop_table("quant_market_dataset")
