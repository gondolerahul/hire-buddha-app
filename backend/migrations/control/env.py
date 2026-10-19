"""Alembic environment of the control tree (``alembic upgrade head``): see ``migrations/envlib.py``."""
from migrations.envlib import CONTROL_TREE, run_env

run_env(CONTROL_TREE)
