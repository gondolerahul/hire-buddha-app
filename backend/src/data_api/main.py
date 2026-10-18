"""The Data API on its own: ``uvicorn src.data_api.main:app`` (image target
``data-api``; ``DATA_API_TENANT_KEY`` pins one business, tech spec §9.1)."""
from src.common.orm_models import import_all_models
from src.data_api.app import create_app

import_all_models()
app = create_app()
