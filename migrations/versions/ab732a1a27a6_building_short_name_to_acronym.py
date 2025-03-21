"""building short_name to acronym

Revision ID: ab732a1a27a6
Revises: b45c77d63c44
Create Date: 2025-03-19 19:41:27.651165

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ab732a1a27a6'
down_revision = 'b45c77d63c44'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('building', schema=None) as batch_op:
        # batch_op.add_column(sa.Column('acronym', sa.String(), nullable=False))
        # batch_op.drop_column('short_name')
        batch_op.alter_column( 'short_name', new_column_name='acronym')
        batch_op.add_column(sa.Column('short_name', sa.String(), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('building', schema=None) as batch_op:
        # batch_op.add_column(sa.Column('short_name', sa.VARCHAR(), autoincrement=False, nullable=False))
        batch_op.drop_column('short_name')
        batch_op.alter_column( 'acronym', new_column_name='short_name')

    # ### end Alembic commands ###
