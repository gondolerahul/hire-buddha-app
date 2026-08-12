"""
embedding_service.py — Centralized Embedding Generation Service

Provides a unified interface for generating embedding vectors, with:
- Admin-configurable embedding model (via IntegrationRegistry)
- Batch embedding with error handling
- Single-node and multi-text embedding methods
- Attributed usage logging (one ``usage_logs`` row per ``embed_batch``)

Cost attribution
----------------
Every Vertex embedding call is metered to ``usage_logs`` with an
``"embedding"`` attribution (see ``services/cost_attribution.py``).
``embed_batch`` is the single chokepoint every caller funnels through,
so the billing write lives there — one row per batch, keyed on the
Vertex-reported ``billable_character_count`` (the unit these models
bill on). The write is best-effort: it runs on its own short-lived
session so it can never commit the caller's in-flight transaction, and
any failure is swallowed so a billing hiccup never breaks retrieval.

Both ingestion-time and retrieval-time embeddings are metered; the
``embedding_phase`` metadata field (``"ingestion"`` vs ``"retrieval"``)
lets the cost dashboard split the two without dropping either.

Used by: knowledge_tree_service, episodic_tree_service, dreaming_engine,
         memory_service (semantic search), graph_service (auto-edges)
"""
import json
import logging
from typing import Any, Dict, List, Optional, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.constants import EMBEDDING_MODEL, EMBEDDING_MODEL_FALLBACK

logger = logging.getLogger(__name__)


async def resolve_embedding_model(db: Any, company_id: UUID) -> tuple[str, Optional[str]]:
    """Phase 11 Track 6 — standalone resolver returning (model_name, api_key).

    This is the public-API form of ``EmbeddingService._resolve_embedding_model``
    so callers that don't want a full EmbeddingService (e.g. a one-off
    cron job) can resolve the per-company embedding model without
    constructing the heavy client.

    Priority is identical to the in-class resolver:
      1. ``ModelTaskDefault`` for ``task_type="embedding"``.
      2. ``IntegrationRegistry`` with ``service_category="EMBEDDING"``.
      3. ``IntegrationRegistry`` Google with ``model_name LIKE '%embed%'``.
      4. ``EMBEDDING_MODEL_FALLBACK`` constant.
    """
    svc = EmbeddingService(db, company_id)
    try:
        model_name = await svc._resolve_embedding_model()
    except Exception:                                                       # pragma: no cover
        model_name = EMBEDDING_MODEL_FALLBACK

    api_key: Optional[str] = None
    try:
        from src.config.models import IntegrationRegistry
        from sqlalchemy import select
        row = (await db.execute(
            select(IntegrationRegistry).where(
                IntegrationRegistry.company_id == company_id,
                IntegrationRegistry.model_name == model_name,
                IntegrationRegistry.status == "active",
            )
        )).scalar_one_or_none()
        if row is not None:
            api_key = getattr(row, "api_key", None)
    except Exception:                                                       # pragma: no cover
        pass
    return model_name, api_key


class EmbeddingService:
    """
    Centralized embedding generation with admin-configurable model,
    batching, and error handling.
    """

    BATCH_SIZE = 100  # Max texts per API call (Vertex AI limit)

    def __init__(self, db: AsyncSession, company_id: UUID) -> None:
        self.db = db
        self.company_id = company_id
        self._client: Any = None
        self._model_name: Optional[str] = None

    async def _get_client_and_model(self) -> tuple[Any, str]:
        """
        Resolve the embedding model and Vertex AI client.

        Priority:
        1. Admin-configured embedding integration (IntegrationRegistry)
        2. Fallback to EMBEDDING_MODEL constant
        """
        if self._client and self._model_name:
            return self._client, self._model_name

        # Try to resolve admin-configured embedding model
        model_name = await self._resolve_embedding_model()

        # Build Vertex AI client (embeddings use v1 stable endpoint)
        from src.common.genai_factory import build_vertex_genai_client
        client = await build_vertex_genai_client(
            self.db, self.company_id,
        )

        self._client = client
        self._model_name = model_name
        return client, model_name

    async def _resolve_embedding_model(self) -> str:
        """
        Resolve embedding model from admin configuration.

        Priority:
        1. ModelTaskDefault for task_type 'embedding' (AI Config page)
        2. IntegrationRegistry with service_category 'EMBEDDING'
        3. IntegrationRegistry with provider 'google' and model matching 'embed'
        4. Fallback to EMBEDDING_MODEL constant
        """
        try:
            # Priority 1: Check AI Config task defaults for 'embedding'
            from src.config.models import ModelTaskDefault as _MTD
            mtd_result = await self.db.execute(
                select(_MTD).where(
                    _MTD.company_id == self.company_id,
                    _MTD.task_type == "embedding",
                )
            )
            mtd = mtd_result.scalar_one_or_none()
            if mtd and mtd.integration_id:
                from src.config.models import IntegrationRegistry as _IR
                ir_result = await self.db.execute(
                    select(_IR).where(
                        _IR.id == mtd.integration_id,
                        _IR.status == "active",
                    )
                )
                ir = ir_result.scalar_one_or_none()
                if ir and ir.model_name:
                    logger.debug(f"Using AI Config task default embedding model: {ir.model_name}")
                    return cast(str, ir.model_name)
        except Exception as e:
            logger.debug(f"ModelTaskDefault lookup for embedding failed: {e}")

        try:
            from src.config.models import IntegrationRegistry

            # Priority 2: Explicit EMBEDDING category
            result = await self.db.execute(
                select(IntegrationRegistry).where(
                    IntegrationRegistry.company_id == self.company_id,
                    IntegrationRegistry.service_category == "EMBEDDING",
                    IntegrationRegistry.status == "active",
                )
            )
            integration = result.scalar_one_or_none()
            if integration and integration.model_name:
                logger.debug(f"Using admin-configured embedding model: {integration.model_name}")
                return cast(str, integration.model_name)

            # Priority 3: Google integration with embed in model name
            # Exclude non-embedding categories to avoid selecting LLM models
            # whose name happens to contain "embed" (e.g. gemini-embedding-2).
            result = await self.db.execute(
                select(IntegrationRegistry).where(
                    IntegrationRegistry.company_id == self.company_id,
                    IntegrationRegistry.provider_name.in_(["google", "gemini"]),
                    IntegrationRegistry.model_name.ilike("%embed%"),
                    IntegrationRegistry.service_category.notin_(
                        ["LLM", "IMAGE_GENERATION", "VOICE"]
                    ),
                    IntegrationRegistry.status == "active",
                )
            )
            integration = result.scalar_one_or_none()
            if integration and integration.model_name:
                logger.debug(f"Using google embedding model: {integration.model_name}")
                return cast(str, integration.model_name)

        except Exception as e:
            logger.debug(f"Failed to resolve embedding model from registry: {e}")

        logger.debug(f"Using fallback embedding model: {EMBEDDING_MODEL}")
        return EMBEDDING_MODEL

    async def embed_text(
        self,
        text: str,
        task_type: str = "RETRIEVAL_DOCUMENT",
    ) -> Optional[List[float]]:
        """
        Embed a single text string.

        Returns embedding vector or None on failure.
        """
        results = await self.embed_batch([text], task_type=task_type)
        return results[0] if results else None

    async def embed_query(self, query: str) -> Optional[List[float]]:
        """Embed a query for search (uses RETRIEVAL_QUERY task type)."""
        return await self.embed_text(query, task_type="RETRIEVAL_QUERY")

    async def embed_batch(
        self,
        texts: List[str],
        task_type: str = "RETRIEVAL_DOCUMENT",
    ) -> List[Optional[List[float]]]:
        """
        Embed a batch of texts. Returns list of embedding vectors.
        None entries indicate failures (logged, not raised).

        Handles batching internally if texts exceed BATCH_SIZE.
        """
        if not texts:
            return []

        try:
            from google.genai import types as _types
            client, model_name = await self._get_client_and_model()
        except Exception as e:
            logger.warning(f"Embedding service unavailable: {e}")
            return [None] * len(texts)

        results: List[Optional[List[float]]] = []
        billable_chars = 0
        token_count = 0
        embedded_count = 0

        # Process in batches
        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i:i + self.BATCH_SIZE]
            batch_results, b_chars, b_tokens, b_ok = await self._embed_batch_internal(
                client, model_name, batch, task_type
            )
            results.extend(batch_results)
            billable_chars += b_chars
            token_count += b_tokens
            embedded_count += b_ok

        # Best-effort attributed billing — one row per embed_batch call.
        # Never blocks the caller's transaction (own session) or raises.
        await self._log_embedding_usage(
            model_name, task_type, billable_chars, token_count, embedded_count,
        )

        return results

    async def _embed_batch_internal(
        self,
        client: Any,
        model_name: str,
        texts: List[str],
        task_type: str,
    ) -> tuple[List[Optional[List[float]]], int, int, int]:
        """Internal: embed a single batch (≤ BATCH_SIZE texts).

        Returns ``(results, billable_chars, token_count, embedded_count)``.
        The character/token tallies feed the attributed usage write in
        :meth:`embed_batch`; Vertex bills embeddings per input character,
        reported on the response as ``metadata.billable_character_count``.
        """
        from google.genai import types as _types

        results: List[Optional[List[float]]] = []
        billable_chars = 0
        token_count = 0
        embedded_count = 0

        for text in texts:
            if not text or not text.strip():
                results.append(None)
                continue

            try:
                # Truncate very long texts (embedding models have limits)
                truncated = text[:8000] if len(text) > 8000 else text

                embed_response = client.models.embed_content(
                    model=model_name,
                    contents=truncated,
                    config=_types.EmbedContentConfig(task_type=task_type),
                )
                embedding = embed_response.embeddings[0].values
                results.append(list(embedding))
                embedded_count += 1

                # Tally the billable unit straight from Vertex's response,
                # falling back to the truncated input length if the SDK
                # omits the metadata.
                meta = getattr(embed_response, "metadata", None)
                resp_chars = getattr(meta, "billable_character_count", None) if meta else None
                billable_chars += int(resp_chars) if resp_chars else len(truncated)
                stats = getattr(embed_response.embeddings[0], "statistics", None)
                resp_tokens = getattr(stats, "token_count", None) if stats else None
                if resp_tokens:
                    token_count += int(resp_tokens)
            except Exception as e:
                logger.warning(f"Embedding failed for text (first 100 chars: {text[:100]!r}): {e}")
                results.append(None)

        return results, billable_chars, token_count, embedded_count

    async def _log_embedding_usage(
        self,
        model_name: str,
        task_type: str,
        billable_chars: int,
        token_count: int,
        embedded_count: int,
    ) -> None:
        """Write one attributed ``usage_logs`` row for an ``embed_batch`` call.

        Best-effort and isolated from the caller:
          * Runs on its own short-lived session so ``UsageService.log_usage``
            (which commits) can never flush the caller's in-flight
            transaction — critical on the retrieval hot path.
          * Swallows every error; a billing failure must never surface
            into embedding/retrieval.
          * Attributes to the live run when one is bound (trace recorder),
            otherwise logs an unscoped (ingestion-cron) charge.

        ``raw_quantity`` is the Vertex-billed character count; the
        ``embedding_phase`` tag lets the dashboard split retrieval-time
        from ingestion-time spend.
        """
        if embedded_count <= 0 or billable_chars <= 0:
            return
        try:
            run_id = None
            try:
                from src.ai.core.trace import current_recorder
                rec = current_recorder()
                if rec is not None:
                    run_id = rec.run_id
            except Exception:
                pass

            phase = "retrieval" if task_type == "RETRIEVAL_QUERY" else "ingestion"

            from src.common.database import AsyncSessionLocal
            from src.ai.usage_service import UsageService
            from src.ai.services.cost_attribution import CostAttribution

            async with AsyncSessionLocal() as sess:
                svc = UsageService(sess)
                await svc.log_usage(
                    company_id=self.company_id,
                    # Embeddings are input-only; follow the platform's
                    # "-in" input-billing SKU convention.
                    service_sku=f"{model_name}-in",
                    raw_quantity=float(billable_chars),
                    execution_id=run_id,
                    metadata={
                        "embedding_model": model_name,
                        "embedding_task_type": task_type,
                        "embedding_phase": phase,
                        "texts_embedded": embedded_count,
                        "billable_characters": int(billable_chars),
                        "token_count": int(token_count),
                    },
                    attribution=CostAttribution.EMBEDDING.value,
                )
        except Exception as exc:                                                # pragma: no cover
            logger.debug("embedding usage logging failed: %s", exc)

    async def embed_node(self, node: Any) -> bool:
        """
        Generate and store embedding for a CortexNode.

        Uses node.summary if available, then node.title, then node.content (truncated).
        Sets node.embedding and node.embedding_model.

        Returns True if embedding was generated, False otherwise.
        """
        text_to_embed = node.summary or node.title
        if not text_to_embed and node.content:
            text_to_embed = node.content[:2000]

        if not text_to_embed:
            return False

        embedding = await self.embed_text(text_to_embed)
        if embedding:
            node.embedding = embedding
            node.embedding_model = self._model_name or EMBEDDING_MODEL
            return True

        return False

    async def embed_nodes_batch(self, nodes: list[Any]) -> int:
        """
        Embed multiple CortexNodes in batch.

        Returns count of successfully embedded nodes.
        """
        texts = []
        valid_nodes = []
        for node in nodes:
            text = node.summary or node.title
            if not text and node.content:
                text = node.content[:2000]
            if text:
                texts.append(text)
                valid_nodes.append(node)

        if not texts:
            return 0

        embeddings = await self.embed_batch(texts)
        model_name = self._model_name or EMBEDDING_MODEL
        count = 0
        for node, embedding in zip(valid_nodes, embeddings):
            if embedding:
                node.embedding = embedding
                node.embedding_model = model_name
                count += 1

        return count

    def get_model_name(self) -> str:
        """Return the resolved embedding model name."""
        return self._model_name or EMBEDDING_MODEL

    async def embed_node_with_edges(self, node: Any) -> bool:
        """
        Embed a node and automatically create similarity edges (Phase E).

        Combines embed_node() with SemanticGraphService.create_similarity_edges()
        for nodes that should be discoverable via the associative graph.
        """
        embedded = await self.embed_node(node)
        if not embedded:
            return False

        try:
            from src.ai.memory.graph_service import SemanticGraphService
            graph = SemanticGraphService(self.db, self.company_id)
            await graph.create_similarity_edges(node.id)
        except Exception as e:
            logger.debug(f"Auto-edge creation failed for node {node.id}: {e}")

        return True

