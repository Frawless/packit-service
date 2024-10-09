"""Add missing value for buildstatus

Revision ID: f376be1907e1
Revises: 3a7e4a388dd2
Create Date: 2024-10-09 09:16:35.149090

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "f376be1907e1"
down_revision = "3a7e4a388dd2"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE buildstatus ADD VALUE 'retry'")

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    pass
    # ### end Alembic commands ###
