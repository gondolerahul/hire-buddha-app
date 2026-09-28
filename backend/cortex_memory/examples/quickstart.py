"""
cortex_memory quickstart — create a tree, write a finding, navigate, search.

Run against any Postgres with the ``vector`` extension:

    pip install cortex-memory
    export CORTEX_DB_URL=postgresql+asyncpg://user:pass@localhost:5432/mydb
    python -m cortex_memory.examples.quickstart

It uses the host-free *reference* providers (hash embeddings, echo LLM); a real
app injects adapters wrapping its own LLM/embedding services.
"""
from __future__ import annotations

import asyncio
import os
from uuid import uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cortex_memory import (
    CortexService,
    KnowledgeTreeService,
    SemanticGraphService,
)
from cortex_memory.providers_reference import EchoLLMProvider, HashEmbeddingProvider
from cortex_memory.schema import create_all_schema_async

# CORTEX node embeddings are Vector(768); match that dimension.
EMBED = HashEmbeddingProvider(dim=768)


async def main() -> None:
    url = os.environ.get("CORTEX_DB_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/cortex")
    engine = create_async_engine(url)
    await create_all_schema_async(engine)  # idempotent

    company = uuid4()
    entity = uuid4()
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as db:
        cortex = CortexService(db, company, llm=EchoLLMProvider())

        # 1. Create a cognitive tree for a task.
        tree = await cortex.create_tree(
            entity_id=entity, user_id=None,
            task_description="Summarise the Q3 board deck",
        )
        await db.commit()
        print(f"tree {tree.id} created (root={tree.root_node_id})")

        # 2. Write a finding under the working-memory root.
        working = await cortex.get_working_root(tree.id)
        node_id = await cortex.write(
            parent_id=working.id, node_type="finding",
            title="Revenue up 12% QoQ",
            content="Q3 revenue grew 12% quarter over quarter, driven by enterprise.",
            summary="Q3 revenue +12% QoQ (enterprise-led).",
        )
        await db.commit()

        # 3. Navigate the working root — the agent sees a bounded viewport.
        viewport = await cortex.navigate(working.id)
        print("viewport children:", [c.title for c in viewport.children])

        # 4. Read the finding back.
        content = await cortex.read(node_id)
        print("read:", content.title, "→", content.content[:60], "...")

        # 5. Ingest a document into the knowledge tree, then semantic-search it.
        ks = KnowledgeTreeService(db, company, embedding=EMBED)
        ktree = await ks.get_or_create_knowledge_tree(entity)
        await db.commit()
        await ks.ingest_document(
            tree_id=ktree.id, document_id=uuid4(), filename="board.md",
            entity_id=entity,
            content="# Board Deck\n\nEnterprise revenue grew 12% with strong net retention.\n",
        )
        await db.commit()

        graph = SemanticGraphService(db, company, embedding=EMBED)
        hits = await graph.semantic_graph_search(query="enterprise revenue", entity_id=entity)
        print(f"semantic search returned {len(hits)} hit(s)")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
