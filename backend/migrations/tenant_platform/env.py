"""Alembic environment of the tenant tree (``alembic -n tenant_platform``): see ``migrations/envlib.py``."""
from migrations.envlib import TENANT_TREE, run_env

run_env(TENANT_TREE)
