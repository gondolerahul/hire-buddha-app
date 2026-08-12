from typing import Optional, Tuple
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from fastapi import HTTPException, status
from src.config.models import IntegrationRegistry, ModelTaskDefault
from src.config.schemas import IntegrationRegistryCreate, IntegrationRegistryUpdate, ModelTaskDefaultCreate
from src.common.security import encrypt_api_key, decrypt_api_key

# ---------------------------------------------------------------------------
# P0.2 — In-process TTL cache for API key resolution.
# Prevents N×6 sequential DB queries per LLM call at high concurrency.
# Requires: pip install cachetools
# ---------------------------------------------------------------------------
try:
    from cachetools import TTLCache
    _API_KEY_CACHE: TTLCache = TTLCache(maxsize=512, ttl=60)
    _CACHE_AVAILABLE = True
except ImportError:
    _API_KEY_CACHE = {}  # type: ignore[assignment]
    _CACHE_AVAILABLE = False


def _cache_bust(company_id: UUID, provider: Optional[str] = None):
    """Remove all cached entries for a company (called on create/update/delete)."""
    if not _CACHE_AVAILABLE:
        return
    prefix = str(company_id)
    stale = [k for k in list(_API_KEY_CACHE.keys()) if k.startswith(prefix)]
    for k in stale:
        _API_KEY_CACHE.pop(k, None)


class ConfigService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # P0.2 — Centralized resolver (replaces per-caller waterfall logic)
    # ------------------------------------------------------------------

    async def resolve_api_key(
        self,
        company_id: UUID,
        provider: str,
        model_name: Optional[str] = None,
    ) -> Optional[str]:
        """
        Single entry-point for API key resolution with TTL caching.

        Resolution order (first match wins):
          1. Exact SKU match (model_name)
          2. SKU match for "{model_name}-in"
          3. Model-name field match
          4. Provider generic key "{provider}-api-key"
          5. Any active key for provider
          6. Case-insensitive provider alias (google ↔ Gemini)

        Results are cached for 60 seconds to avoid repeated DB queries.
        Cache is invalidated when integration entries are mutated.
        """
        cache_key = f"{company_id}:{provider}:{model_name or ''}"
        if _CACHE_AVAILABLE and cache_key in _API_KEY_CACHE:
            return _API_KEY_CACHE[cache_key]

        key: Optional[str] = None

        if model_name:
            key = await self.get_api_key_by_sku(company_id, model_name)
            if not key:
                key = await self.get_api_key_by_sku(company_id, f"{model_name}-in")
            if not key:
                key = await self.get_api_key_by_model(company_id, model_name)

        if not key:
            key = await self.get_api_key_by_sku(company_id, f"{provider}-api-key")
        if not key:
            key = await self.get_api_key_by_provider(company_id, provider)
        if not key:
            # Case-insensitive alias: google ↔ Gemini
            alias = "google" if provider.lower() == "gemini" else (
                "Gemini" if provider.lower() == "google" else None
            )
            if alias:
                key = await self.get_api_key_by_provider(company_id, alias)

        if key and _CACHE_AVAILABLE:
            _API_KEY_CACHE[cache_key] = key

        return key

    async def create_registry_entry(self, entry_in: IntegrationRegistryCreate) -> IntegrationRegistry:
        encrypted_key = encrypt_api_key(entry_in.api_key)
        
        entry_data = entry_in.model_dump(exclude={"api_key"})
        entry = IntegrationRegistry(
            **entry_data,
            encrypted_api_key=encrypted_key
        )
        self.db.add(entry)
        await self.db.commit()
        await self.db.refresh(entry)
        # Invalidate API key cache for this company
        _cache_bust(entry.company_id)
        return entry

    async def get_registry_entries(self, company_id: Optional[UUID] = None) -> list[IntegrationRegistry]:
        query = select(IntegrationRegistry)
        if company_id:
            query = query.where(IntegrationRegistry.company_id == company_id)
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_registry_entry(self, entry_id: UUID) -> IntegrationRegistry:
        result = await self.db.execute(
            select(IntegrationRegistry).where(IntegrationRegistry.id == entry_id)
        )
        entry = result.scalar_one_or_none()
        if not entry:
            raise HTTPException(status_code=404, detail="Registry entry not found")
        return entry

    async def update_registry_entry(self, entry_id: UUID, entry_in: IntegrationRegistryUpdate) -> IntegrationRegistry:
        entry = await self.get_registry_entry(entry_id)
        
        update_data = entry_in.model_dump(exclude_unset=True)
        if "api_key" in update_data:
            update_data["encrypted_api_key"] = encrypt_api_key(update_data.pop("api_key"))
        
        for field, value in update_data.items():
            setattr(entry, field, value)
        
        await self.db.commit()
        await self.db.refresh(entry)
        # Invalidate API key cache for this company
        _cache_bust(entry.company_id)
        return entry

    async def delete_registry_entry(self, entry_id: UUID) -> bool:
        entry = await self.get_registry_entry(entry_id)
        company_id = entry.company_id
        await self.db.delete(entry)
        await self.db.commit()
        # Invalidate API key cache for this company
        _cache_bust(company_id)
        return True

    async def _get_app_company_id(self) -> Optional[UUID]:
        """Get the ID of the platform (APP) company."""
        from src.auth.models import Company
        result = await self.db.execute(
            select(Company.id).where(Company.type == "APP").limit(1)
        )
        return result.scalar_one_or_none()

    async def get_api_key_by_sku(self, company_id: UUID, service_sku: str) -> str:
        # 1. Try company-specific key
        result = await self.db.execute(
            select(IntegrationRegistry).where(
                IntegrationRegistry.company_id == company_id,
                IntegrationRegistry.service_sku == service_sku,
                IntegrationRegistry.status == "active"
            )
        )
        entry = result.scalar_one_or_none()
        
        # 2. Try APP company fallback
        if not entry:
            app_company_id = await self._get_app_company_id()
            if app_company_id and app_company_id != company_id:
                result = await self.db.execute(
                    select(IntegrationRegistry).where(
                        IntegrationRegistry.company_id == app_company_id,
                        IntegrationRegistry.service_sku == service_sku,
                        IntegrationRegistry.status == "active"
                    )
                )
                entry = result.scalar_one_or_none()

        if not entry or not entry.encrypted_api_key:
            return None
        return decrypt_api_key(entry.encrypted_api_key)

    async def get_api_key_by_model(self, company_id: UUID, model_name: str) -> str:
        """
        Find an API key by searching for the exact model_name.
        """
        # 1. Try company-specific
        result = await self.db.execute(
            select(IntegrationRegistry)
            .where(
                IntegrationRegistry.company_id == company_id,
                IntegrationRegistry.model_name == model_name,
                IntegrationRegistry.status == "active",
                IntegrationRegistry.encrypted_api_key.isnot(None)
            )
        )
        entry = result.scalars().first()
        
        # 2. Try APP company fallback
        if not entry:
            app_company_id = await self._get_app_company_id()
            if app_company_id and app_company_id != company_id:
                result = await self.db.execute(
                    select(IntegrationRegistry)
                    .where(
                        IntegrationRegistry.company_id == app_company_id,
                        IntegrationRegistry.model_name == model_name,
                        IntegrationRegistry.status == "active",
                        IntegrationRegistry.encrypted_api_key.isnot(None)
                    )
                )
                entry = result.scalars().first()

        if not entry or not entry.encrypted_api_key:
            return None
        return decrypt_api_key(entry.encrypted_api_key)

    async def get_api_key_by_provider(self, company_id: UUID, provider_name: str) -> str:
        """
        Find any API key for a given provider (e.g., 'google', 'openai').
        Falls back to finding any active integration for that provider.
        """
        # 1. Try company-specific
        result = await self.db.execute(
            select(IntegrationRegistry).where(
                IntegrationRegistry.company_id == company_id,
                IntegrationRegistry.provider_name == provider_name,
                IntegrationRegistry.status == "active",
                IntegrationRegistry.encrypted_api_key.isnot(None)
            )
        )
        entry = result.scalars().first()
        
        # 2. Try APP company fallback
        if not entry:
            app_company_id = await self._get_app_company_id()
            if app_company_id and app_company_id != company_id:
                result = await self.db.execute(
                    select(IntegrationRegistry).where(
                        IntegrationRegistry.company_id == app_company_id,
                        IntegrationRegistry.provider_name == provider_name,
                        IntegrationRegistry.status == "active",
                        IntegrationRegistry.encrypted_api_key.isnot(None)
                    )
                )
                entry = result.scalars().first()

        if not entry or not entry.encrypted_api_key:
            return None
        return decrypt_api_key(entry.encrypted_api_key)

    async def get_integration_by_sku(self, company_id: UUID, service_sku: str) -> Optional[IntegrationRegistry]:
        """Get the full integration entry by SKU with platform fallback."""
        # 1. Company specific
        result = await self.db.execute(
            select(IntegrationRegistry).where(
                IntegrationRegistry.company_id == company_id,
                IntegrationRegistry.service_sku == service_sku,
                IntegrationRegistry.status == "active"
            )
        )
        entry = result.scalar_one_or_none()
        if entry: return entry

        # 2. Platform fallback
        app_company_id = await self._get_app_company_id()
        if app_company_id and app_company_id != company_id:
            result = await self.db.execute(
                select(IntegrationRegistry).where(
                    IntegrationRegistry.company_id == app_company_id,
                    IntegrationRegistry.service_sku == service_sku,
                    IntegrationRegistry.status == "active"
                )
            )
            return result.scalar_one_or_none()
        return None

    async def get_integration_by_provider(self, company_id: UUID, provider_name: str) -> Optional[IntegrationRegistry]:
        """Get the full integration entry by provider with platform fallback."""
        # 1. Company specific
        result = await self.db.execute(
            select(IntegrationRegistry).where(
                IntegrationRegistry.company_id == company_id,
                IntegrationRegistry.provider_name.ilike(f"%{provider_name}%"),
                IntegrationRegistry.status == "active"
            )
        )
        entry = result.scalars().first()
        if entry: return entry

        # 2. Platform fallback
        app_company_id = await self._get_app_company_id()
        if app_company_id and app_company_id != company_id:
            result = await self.db.execute(
                select(IntegrationRegistry).where(
                    IntegrationRegistry.company_id == app_company_id,
                    IntegrationRegistry.provider_name.ilike(f"%{provider_name}%"),
                    IntegrationRegistry.status == "active"
                )
            )
            return result.scalars().first()
        return None

    # ------------------------------------------------------------------
    # ModelTaskDefault CRUD — maps task types to model integrations
    # ------------------------------------------------------------------

    async def set_task_default(
        self,
        company_id: UUID,
        task_type: str,
        integration_id: UUID,
        routing_mode: str = "single",
    ) -> ModelTaskDefault:
        """
        Upsert the default model for a given task type.
        Creates if not exists, updates if already set.
        """
        # Verify integration exists and belongs to this company (or APP company)
        result = await self.db.execute(
            select(IntegrationRegistry).where(
                IntegrationRegistry.id == integration_id,
                IntegrationRegistry.status == "active"
            )
        )
        integration = result.scalar_one_or_none()
        if not integration:
            raise HTTPException(status_code=404, detail="Integration not found or inactive")

        # Check for existing entry
        existing_result = await self.db.execute(
            select(ModelTaskDefault).where(
                and_(
                    ModelTaskDefault.company_id == company_id,
                    ModelTaskDefault.task_type == task_type,
                )
            )
        )
        existing = existing_result.scalar_one_or_none()

        if existing:
            existing.integration_id = integration_id
            existing.routing_mode = routing_mode
            await self.db.commit()
            await self.db.refresh(existing)
            return existing
        else:
            new_default = ModelTaskDefault(
                company_id=company_id,
                task_type=task_type,
                integration_id=integration_id,
                routing_mode=routing_mode,
            )
            self.db.add(new_default)
            await self.db.commit()
            await self.db.refresh(new_default)
            return new_default

    async def get_task_default(
        self, company_id: UUID, task_type: str
    ) -> Optional[ModelTaskDefault]:
        """
        Get the configured default model for a task type.
        Falls back to APP company defaults if company has no specific config.
        """
        # 1. Company-specific
        result = await self.db.execute(
            select(ModelTaskDefault).where(
                and_(
                    ModelTaskDefault.company_id == company_id,
                    ModelTaskDefault.task_type == task_type,
                )
            )
        )
        entry = result.scalar_one_or_none()
        if entry:
            return entry

        # 2. APP company fallback
        app_company_id = await self._get_app_company_id()
        if app_company_id and app_company_id != company_id:
            result = await self.db.execute(
                select(ModelTaskDefault).where(
                    and_(
                        ModelTaskDefault.company_id == app_company_id,
                        ModelTaskDefault.task_type == task_type,
                    )
                )
            )
            return result.scalar_one_or_none()

        return None

    async def get_all_task_defaults(self, company_id: UUID) -> list[ModelTaskDefault]:
        """List all task defaults visible to a company (own + APP company)."""
        result = await self.db.execute(
            select(ModelTaskDefault).where(
                ModelTaskDefault.company_id == company_id
            )
        )
        own = list(result.scalars().all())

        app_company_id = await self._get_app_company_id()
        if app_company_id and app_company_id != company_id:
            result = await self.db.execute(
                select(ModelTaskDefault).where(
                    ModelTaskDefault.company_id == app_company_id
                )
            )
            app_defaults = list(result.scalars().all())
            # Merge: company-specific overrides APP defaults for same task_type
            own_tasks = {d.task_type for d in own}
            for ad in app_defaults:
                if ad.task_type not in own_tasks:
                    own.append(ad)

        return own

    async def delete_task_default(self, company_id: UUID, task_type: str) -> bool:
        """Remove a task default configuration."""
        result = await self.db.execute(
            select(ModelTaskDefault).where(
                and_(
                    ModelTaskDefault.company_id == company_id,
                    ModelTaskDefault.task_type == task_type,
                )
            )
        )
        entry = result.scalar_one_or_none()
        if not entry:
            raise HTTPException(status_code=404, detail=f"No default configured for task '{task_type}'")
        await self.db.delete(entry)
        await self.db.commit()
        return True

    async def resolve_model_for_task(
        self, company_id: UUID, task_type: str
    ) -> Tuple[Optional[IntegrationRegistry], Optional[str]]:
        """
        Core resolution method used by the LLM Router.

        Returns:
            (integration_entry, decrypted_api_key) or (None, None) if not configured.
        """
        task_default = await self.get_task_default(company_id, task_type)
        if not task_default:
            return None, None

        # Load the integration
        result = await self.db.execute(
            select(IntegrationRegistry).where(
                IntegrationRegistry.id == task_default.integration_id,
                IntegrationRegistry.status == "active"
            )
        )
        integration = result.scalar_one_or_none()
        if not integration:
            return None, None

        api_key = None
        if integration.encrypted_api_key:
            api_key = decrypt_api_key(integration.encrypted_api_key)

        return integration, api_key

