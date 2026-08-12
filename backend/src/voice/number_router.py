"""
Number Router for dynamic phone number assignment and routing.

Uses the unified PhoneNumber model. Call routing queries filter by
status='assigned' + is_active=True.
"""
import logging
from uuid import UUID
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.voice.phone_pool_models import PhoneNumber

logger = logging.getLogger(__name__)


class NumberRouter:
    """
    Manages phone number assignments and routing logic.

    Operates against the unified phone_numbers table.
    Call routing targets numbers with status='assigned' + is_active=True.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def find_customer_by_number(
        self,
        phone_number: str
    ) -> Optional[PhoneNumber]:
        """
        Find assigned phone number entry for a given phone number.
        Used by incoming call webhooks to determine routing.

        Normalizes the input to handle format mismatches between providers
        (e.g., Tata Tele sends '+918065251146' but DB may store '918065251146').

        Args:
            phone_number: Phone number that was called (e.g., "+911234567890")

        Returns:
            PhoneNumber object if found, None otherwise
        """
        if not phone_number:
            return None

        # Normalize: strip whitespace, dashes
        clean = phone_number.replace(" ", "").replace("-", "")

        # Build candidate list: original, without '+', with '+'
        candidates = [clean]
        if clean.startswith("+"):
            candidates.append(clean[1:])   # '+918065251146' → '918065251146'
        else:
            candidates.append(f"+{clean}")  # '918065251146' → '+918065251146'

        from sqlalchemy import or_
        result = await self.db.execute(
            select(PhoneNumber).where(
                or_(*[PhoneNumber.phone_number == c for c in candidates]),
                PhoneNumber.status == "assigned",
                PhoneNumber.is_active == True
            )
        )
        assignment = result.scalar_one_or_none()

        if assignment:
            logger.info(f"Found customer {assignment.customer_id} for number {phone_number}")
        else:
            logger.warning(f"No assigned number found for {phone_number} (tried: {candidates})")

        return assignment

    async def assign_number_to_customer(
        self,
        company_id: UUID,
        customer_id: UUID,
        customer_name: str,
        agent_id: UUID,
        phone_number: str,
        provider: Optional[str] = None,
        customer_metadata: Optional[dict] = None
    ) -> PhoneNumber:
        """
        Assign a phone number to a customer (move to 'assigned' status).

        If the number already exists in the pool, transition its status.
        If not, create a new entry directly as 'assigned'.

        Args:
            company_id: Company UUID
            customer_id: Customer UUID
            customer_name: Customer name for reference
            agent_id: Agent (HierarchicalEntity) to handle calls
            phone_number: Phone number to assign
            provider: 'twilio' or 'tata_tele' (auto-detected if None)
            customer_metadata: Additional customer information

        Returns:
            Updated/created PhoneNumber
        """
        from datetime import datetime

        # Auto-detect provider based on country code if not specified
        if provider is None:
            provider = self._detect_provider(phone_number)

        # Check if number already exists
        result = await self.db.execute(
            select(PhoneNumber).where(PhoneNumber.phone_number == phone_number)
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Transition existing number to assigned
            existing.status = "assigned"
            existing.company_id = company_id
            existing.customer_id = customer_id
            existing.customer_name = customer_name
            existing.agent_id = agent_id
            existing.customer_metadata = customer_metadata or {}
            existing.assigned_at = datetime.utcnow()
            existing.is_active = True
            await self.db.commit()
            await self.db.refresh(existing)
            logger.info(
                f"Assigned existing number {phone_number} ({provider}) to "
                f"customer {customer_id} with agent {agent_id}"
            )
            return existing

        # Create new entry as assigned
        entry = PhoneNumber(
            phone_number=phone_number,
            provider=provider,
            country_code=self._detect_country_code(phone_number),
            status="assigned",
            company_id=company_id,
            customer_id=customer_id,
            customer_name=customer_name,
            agent_id=agent_id,
            customer_metadata=customer_metadata or {},
            assigned_at=datetime.utcnow(),
            claimed_at=datetime.utcnow(),
            is_active=True,
        )

        self.db.add(entry)
        await self.db.commit()
        await self.db.refresh(entry)

        logger.info(
            f"Created+assigned number {phone_number} ({provider}) to "
            f"customer {customer_id} with agent {agent_id}"
        )

        return entry

    def _detect_provider(self, phone_number: str) -> str:
        """
        Detect provider based on phone number country code.
        """
        clean_number = phone_number.replace(" ", "").replace("-", "")

        # India: +91
        if clean_number.startswith("+91"):
            return "tata_tele"

        # Default to Twilio for other countries
        return "twilio"

    def _detect_country_code(self, phone_number: str) -> str:
        """Detect country code from E.164 number."""
        clean = phone_number.replace(" ", "").replace("-", "")
        if clean.startswith("+91"):
            return "+91"
        elif clean.startswith("+44"):
            return "+44"
        elif clean.startswith("+1"):
            return "+1"
        elif clean.startswith("+"):
            return clean[:3] if len(clean) > 10 else clean[:2]
        return "+91"  # default

    async def get_customer_number(
        self,
        customer_id: UUID
    ) -> Optional[PhoneNumber]:
        """
        Get assigned phone number for a customer.
        """
        result = await self.db.execute(
            select(PhoneNumber).where(
                PhoneNumber.customer_id == customer_id,
                PhoneNumber.status == "assigned",
                PhoneNumber.is_active == True
            )
        )
        return result.scalar_one_or_none()

    async def deactivate_number_assignment(
        self,
        phone_number: str
    ) -> None:
        """
        Deactivate a number assignment — move back to 'claimed' (soft unassign).
        """
        result = await self.db.execute(
            select(PhoneNumber).where(
                PhoneNumber.phone_number == phone_number
            )
        )
        entry = result.scalar_one_or_none()

        if entry:
            entry.status = "claimed"
            entry.agent_id = None
            entry.customer_id = None
            entry.customer_name = None
            entry.assigned_at = None
            await self.db.commit()
            logger.info(f"Unassigned number: {phone_number} → claimed")

    async def get_company_number(
        self,
        company_id: UUID,
        provider: str = "twilio",
        agent_id: Optional[UUID] = None,
    ) -> Optional[PhoneNumber]:
        """
        Get company's assigned phone number for outbound calls.

        When agent_id is provided, returns the number assigned to that
        specific agent — this ensures campaign calls use the correct
        caller ID matching the campaign's voice agent.

        Falls back to any active assigned company number if no
        agent-specific number is found.
        """
        # Strategy 1: Look up number assigned to the specific agent
        if agent_id:
            result = await self.db.execute(
                select(PhoneNumber).where(
                    PhoneNumber.company_id == company_id,
                    PhoneNumber.provider == provider,
                    PhoneNumber.agent_id == agent_id,
                    PhoneNumber.status == "assigned",
                    PhoneNumber.is_active == True
                ).limit(1)
            )
            assignment = result.scalar_one_or_none()
            if assignment:
                logger.info(
                    f"Resolved agent-specific number {assignment.phone_number} "
                    f"for agent {agent_id}"
                )
                return assignment
            logger.warning(
                f"No {provider} number assigned to agent {agent_id}, "
                f"falling back to company-level lookup"
            )

        # Strategy 2: Fallback — first active assigned company number
        result = await self.db.execute(
            select(PhoneNumber).where(
                PhoneNumber.company_id == company_id,
                PhoneNumber.provider == provider,
                PhoneNumber.status == "assigned",
                PhoneNumber.is_active == True
            ).limit(1)
        )
        assignment = result.scalar_one_or_none()

        if not assignment:
            logger.warning(
                f"No active assigned {provider} number found for company {company_id}"
            )

        return assignment

    async def list_active_assignments(
        self,
        company_id: UUID,
        limit: int = 100,
        offset: int = 0
    ) -> list[PhoneNumber]:
        """
        List all assigned numbers for a company.
        """
        result = await self.db.execute(
            select(PhoneNumber)
            .where(
                PhoneNumber.company_id == company_id,
                PhoneNumber.status == "assigned",
                PhoneNumber.is_active == True
            )
            .limit(limit)
            .offset(offset)
            .order_by(PhoneNumber.assigned_at.desc())
        )
        return result.scalars().all()
