"""将 Agent 目录中的核心可得指标纳入正式指标字典。"""

from alembic import op
import sqlalchemy as sa

revision = "0013_seed_agent_metrics"
down_revision = "0012_thesis_kind"
branch_labels = None
depends_on = None

_METRICS = (
    ("AUTO-SALES-M", "月度汽车销量", "辆", "月", "月度", "公司月度产销公告披露的汽车销量。", "company-ir"),
    ("AUTO-EXPORT-SALES-M", "月度海外销量/出口量", "辆", "月", "月度", "月度公告披露的出口或海外销量。", "company-ir"),
    ("AUTO-BATTERY-INSTALL-M", "动力及储能电池装机量", "GWh", "月", "月度", "月度产销公告披露的动力电池与储能电池装机总量。", "company-ir"),
    ("FIN-REVENUE-Q", "单季度营业收入", "元", "随财报", "单季度", "财报披露的单季度营业收入。", "eastmoney-financial-api"),
    ("FIN-NET-PROFIT-Q", "单季度归母净利润", "元", "随财报", "单季度", "财报披露的单季度归母净利润。", "tushare-pro"),
)


def upgrade() -> None:
    metric = sa.table(
        "metric",
        sa.column("metric_id", sa.String), sa.column("version", sa.String),
        sa.column("name", sa.String), sa.column("unit", sa.String),
        sa.column("frequency", sa.String), sa.column("period_type", sa.String),
        sa.column("definition", sa.Text), sa.column("source_id", sa.String),
        sa.column("expected_direction", sa.String), sa.column("status", sa.String),
        sa.column("allow_yoy", sa.Boolean), sa.column("allow_qoq", sa.Boolean), sa.column("allow_peer", sa.Boolean),
    )
    conn = op.get_bind()
    for row in _METRICS:
        exists = conn.execute(sa.text("select 1 from metric where metric_id=:id and version='v1.0'"), {"id": row[0]}).scalar()
        if not exists:
            conn.execute(metric.insert().values(metric_id=row[0], version="v1.0", name=row[1], unit=row[2], frequency=row[3], period_type=row[4], definition=row[5], source_id=row[6], expected_direction="越高越好", status="待确认", allow_yoy=True, allow_qoq=True, allow_peer=False))


def downgrade() -> None:
    op.execute(sa.text("delete from metric where metric_id in ('AUTO-SALES-M','AUTO-EXPORT-SALES-M','AUTO-BATTERY-INSTALL-M','FIN-REVENUE-Q','FIN-NET-PROFIT-Q') and version='v1.0'"))
