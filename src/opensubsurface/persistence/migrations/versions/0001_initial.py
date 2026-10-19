"""Initial immutable-object ledger schema; legacy development schema adoption checked explicitly."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    expected = {
        "projects": {"id", "data"},
        "objects": {"id", "revision", "project_id", "kind", "data"},
        "jobs": {"id", "project_id", "operation", "key", "payload_hash", "data"},
        "uploads": {"id", "project_id", "data"},
        "state": {"id", "data"},
    }
    existing = set(inspector.get_table_names()) - {"alembic_version"}
    if existing:
        if existing != set(expected) or any(
            {col["name"] for col in inspector.get_columns(table)} != columns
            for table, columns in expected.items()
        ):
            raise RuntimeError("Unknown database schema; automatic migration is not allowed")
        return
    op.create_table("projects", sa.Column("id", sa.String, primary_key=True), sa.Column("data", sa.String))
    op.create_table(
        "objects",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("revision", sa.Integer, primary_key=True),
        sa.Column("project_id", sa.String),
        sa.Column("kind", sa.String),
        sa.Column("data", sa.String),
    )
    op.create_index("ix_objects_project_id", "objects", ["project_id"])
    op.create_table(
        "jobs",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("project_id", sa.String),
        sa.Column("operation", sa.String),
        sa.Column("key", sa.String),
        sa.Column("payload_hash", sa.String),
        sa.Column("data", sa.String),
        sa.UniqueConstraint("project_id", "operation", "key"),
    )
    op.create_index("ix_jobs_project_id", "jobs", ["project_id"])
    op.create_table(
        "uploads",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("project_id", sa.String),
        sa.Column("data", sa.String),
    )
    op.create_table("state", sa.Column("id", sa.String, primary_key=True), sa.Column("data", sa.String))


def downgrade():
    raise RuntimeError("Destructive downgrade is not allowed; restore a backup into a separate directory")
