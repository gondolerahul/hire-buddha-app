# backend/scripts/migrations/

One-off data migrations. Each script is idempotent.

Run from the repo root with the backend virtualenv activated:

```
cd backend
source .venv/bin/activate
python -m backend.scripts.migrations.<name>
```

| Script | Purpose |
|--------|---------|
| `documents_to_knowledge_trees.py` | Backfill v2 Knowledge Trees from legacy `document_chunks` rows. |
| `episodic_to_trees.py` | Backfill v2 Episodic Trees from legacy `episodic_memories` rows. |

These are post-deploy migrations, not Alembic schema migrations. Alembic
schema migrations live under `backend/migrations/`.
