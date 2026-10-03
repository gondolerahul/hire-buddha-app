from typing import Optional, Tuple
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from fastapi import HTTPException, status
from src.config.models import IntegrationRegistry, ModelTaskDefault, ServiceCategory
from src.config.schemas import IntegrationRegistryCreate, IntegrationRegistryUpdate, ModelTaskDefaultCreate
from src.common.security import encrypt_api_key, decrypt_api_key

from src.config.resolution_cache import ResolutionCache, bump_generation, current_generation

# Key lookups, valid while the integration generation is (LP-22): a write here
# makes every process re-resolve within a second, not just this one.
_API_KEYS = ResolutionCache(maxsize=512)


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

        Results are cached until a registry write changes the integration
        generation (every process), or 60 s when Redis cannot be read.
        """
        cache_key = (company_id, provider, model_name or "")
        generation = await current_generation()
        cached = _API_KEYS.get(cache_key, generation)
        if cached is not ResolutionCache.MISS:
            return cached

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

        if key:
            _API_KEYS.put(cache_key, key, generation)

        return key

    async def create_registry_entry(self, entry_in: IntegrationRegistryCreate) -> IntegrationRegistry:
        entry_data = entry_in.model_dump(exclude={"api_key"})
        api_key = entry_in.api_key
        if entry_data.get("provider_name") == "tata_tele":
            # Secrets typed into the metadata JSON are encrypted, never stored plain.
            from src.voice.tata_credentials import normalize_tata_metadata
            entry_data["service_metadata"], meta_key = normalize_tata_metadata(entry_data.get("service_metadata"))
            api_key = api_key or meta_key
        encrypted_key = encrypt_api_key(api_key) if api_key else None  # none for ADC (LP-12)

        entry = IntegrationRegistry(
            **entry_data,
            encrypted_api_key=encrypted_key
        )
        self.db.add(entry)
        await self.db.commit()
        await self.db.refresh(entry)
        await bump_generation()
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
        provider = update_data.get("provider_name") or entry.provider_name
        if provider == "tata_tele" and "service_metadata" in update_data:
            # Keep the stored secrets the console never sees; encrypt any it sends.
            from src.voice.tata_credentials import normalize_tata_metadata
            update_data["service_metadata"], meta_key = normalize_tata_metadata(
                update_data["service_metadata"], entry.service_metadata,
            )
            if meta_key and not update_data.get("api_key"):
                update_data["api_key"] = meta_key
        if "api_key" in update_data:
            update_data["encrypted_api_key"] = encrypt_api_key(update_data.pop("api_key"))
        
        for field, value in update_data.items():
            setattr(entry, field, value)
        
        await self.db.commit()
        await self.db.refresh(entry)
        await bump_generation()
        return entry

    async def delete_registry_entry(self, entry_id: UUID) -> bool:
        entry = await self.get_registry_entry(entry_id)
        await self.db.delete(entry)
        await self.db.commit()
        await bump_generation()
        return True

    async def _get_app_company_id(self) -> Optional[UUID]:
        """Get the ID of the platform (APP) company."""
        from src.auth.platform import platform_company_id
        return await platform_company_id(self.db)

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
        """The company's active integration of exactly this provider (case-folded),
        else the platform's; the most recently updated row wins. It used to be
        ``ILIKE '%name%'`` with no order, so ``google`` could pick up any
        provider whose name contains it (LP-21)."""
        owners = [company_id]
        app_company_id = await self._get_app_company_id()
        if app_company_id and app_company_id != company_id:
            owners.append(app_company_id)
        for owner in owners:
            entry = (await self.db.execute(
                select(IntegrationRegistry).where(
                    IntegrationRegistry.company_id == owner,
                    func.lower(IntegrationRegistry.provider_name) == provider_name.lower(),
                    IntegrationRegistry.status == "active",
                ).order_by(IntegrationRegistry.updated_at.desc(), IntegrationRegistry.id).limit(1)
            )).scalar_one_or_none()
            if entry:
                return entry
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
            await bump_generation()
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
            await bump_generation()
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
        await bump_generation()
        return True

    async def resolve_model_by_name(
        self, company_id: UUID, model_name: str
    ) -> Tuple[Optional[IntegrationRegistry], Optional[str]]:
        """The integration that serves ``model_name`` — the company's, else the
        platform's — as ``(integration, api_key)``, or ``(None, None)``.

        A model is usable only when it can be billed: its ``<model>-in`` and
        ``<model>-out`` SKUs are both active in the same company (LP-05). An
        entity's ``model_override`` resolves here, so it brings its own
        provider and credentials instead of borrowing the task default's.
        """
        owners = [company_id]
        app_company_id = await self._get_app_company_id()
        if app_company_id and app_company_id != company_id:
            owners.append(app_company_id)
        for owner in owners:
            rows = (await self.db.execute(
                select(IntegrationRegistry).where(
                    IntegrationRegistry.company_id == owner,
                    IntegrationRegistry.model_name == model_name,
                    IntegrationRegistry.service_category == ServiceCategory.LLM,
                    IntegrationRegistry.status == "active",
                )
            )).scalars().all()
            skus = {r.service_sku for r in rows}
            if f"{model_name}-in" not in skus or f"{model_name}-out" not in skus:
                continue
            row = next((r for r in rows if r.encrypted_api_key), rows[0])
            return row, decrypt_api_key(row.encrypted_api_key) if row.encrypted_api_key else None
        return None, None

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

