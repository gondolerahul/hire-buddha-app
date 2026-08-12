"""
Campaign Service for managing voice calling campaigns.

Handles:
- Campaign CRUD operations
- Contact list management (CSV/Excel upload)
- Campaign execution
- Status tracking
"""
import logging
import csv
import io
from datetime import datetime
from uuid import UUID
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from fastapi import UploadFile

from src.ai.campaign_models import Campaign, CampaignCall

logger = logging.getLogger(__name__)


class CampaignService:
    """Service for campaign management."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_campaign(
        self,
        company_id: UUID,
        created_by: UUID,
        agent_id: UUID,
        name: str,
        contact_list: List[Dict[str, Any]],
        description: Optional[str] = None,
        provider: str = "twilio",
        call_script_template: Optional[str] = None,
        scheduled_start: Optional[datetime] = None,
        scheduled_end: Optional[datetime] = None,
        max_concurrent_calls: int = 5,
        max_calls_per_hour: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Campaign:
        """
        Create a new campaign.
        
        Args:
            company_id: Company UUID
            created_by: User UUID
            agent_id: Agent (HierarchicalEntity) UUID
            name: Campaign name
            contact_list: List of contact dicts with phone, name,  etc.
            description: Campaign description
            provider: 'twilio' or 'tata_tele'
            call_script_template: Custom script template
            scheduled_start: When to start calling
            scheduled_end: When to stop calling
            max_concurrent_calls: Max simultaneous calls
            max_calls_per_hour: Rate limit
            metadata: Additional metadata
            
        Returns:
            Created Campaign object
        """
        campaign = Campaign(
            company_id=company_id,
            created_by=created_by,
            agent_id=agent_id,
            name=name,
            description=description,
            total_contacts=len(contact_list),
            contact_list=contact_list,
            provider=provider,
            call_script_template=call_script_template,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
            max_concurrent_calls=max_concurrent_calls,
            max_calls_per_hour=max_calls_per_hour,
            status="draft",
            campaign_metadata=metadata or {}
        )
        
        self.db.add(campaign)
        await self.db.commit()
        await self.db.refresh(campaign)
        
        # Create CampaignCall records for each contact
        await self._create_campaign_calls(campaign.id, contact_list)
        
        logger.info(f"Created campaign {campaign.id} with {len(contact_list)} contacts")
        return campaign
    
    async def _create_campaign_calls(
        self,
        campaign_id: UUID,
        contact_list: List[Dict[str, Any]]
    ):
        """
        Create CampaignCall records for each contact.
        
        Args:
            campaign_id: Campaign UUID
            contact_list: List of contact dicts
        """
        campaign_calls = [
            CampaignCall(
                campaign_id=campaign_id,
                contact_data=contact,
                status="pending"
            )
            for contact in contact_list
        ]
        
        self.db.add_all(campaign_calls)
        await self.db.commit()
        
        logger.info(f"Created {len(campaign_calls)} campaign call records")
    
    async def parse_csv(self, file: UploadFile) -> List[Dict[str, Any]]:
        """
        Parse uploaded CSV file into contact list with robust encoding and delimiter detection.
        """
        try:
            contents = await file.read()
            # Handle BOM by using utf-8-sig
            try:
                decoded = contents.decode("utf-8-sig")
            except UnicodeDecodeError:
                decoded = contents.decode("latin-1")
            
            # Detect delimiter
            sample = decoded[:2048]
            delimiter = ","
            if sample:
                try:
                    dialect = csv.Sniffer().sniff(sample)
                    delimiter = dialect.delimiter
                except Exception:
                    # Fallback to common delimiters if sniffer fails
                    if ";" in sample and "," not in sample:
                        delimiter = ";"
            
            f = io.StringIO(decoded)
            csv_reader = csv.DictReader(f, delimiter=delimiter)
            
            contacts = []
            for row in csv_reader:
                # Clean row: strip spaces from keys and values
                # Also filter out None keys (happens with trailing commas)
                clean_row = {
                    (str(k).strip() if k else k): (str(v).strip() if v else v)
                    for k, v in row.items()
                    if k is not None
                }
                if any(clean_row.values()): # Skip empty rows
                    contacts.append(clean_row)
            
            if contacts:
                logger.info(f"Parsed {len(contacts)} contacts. Delimiter: '{delimiter}'. Headers: {list(contacts[0].keys())}")
            else:
                logger.warning("CSV parsed but no contacts found")
                
            return contacts
        except Exception as e:
            logger.error(f"Failed to parse CSV: {e}")
            raise ValueError(f"Invalid CSV format: {str(e)}")
    
    async def validate_contacts(
        self,
        contacts: List[Dict[str, Any]],
        required_fields: List[str] = None
    ) -> Dict[str, Any]:
        """
        Validate contact list.
        
        Args:
            contacts: List of contact dicts
            required_fields: Required fields (default: ['phone'])
            
        Returns:
            Validation result with errors
        """
        if required_fields is None:
            required_fields = ['phone']
        
        errors = []
        valid_contacts = []
        
        for idx, contact in enumerate(contacts):
            # Check required fields
            # We use case-insensitive check for 'phone'
            phone_key = next((k for k in contact.keys() if k.lower() == 'phone'), 'phone')
            
            missing_fields = [f for f in required_fields if (f == 'phone' and not contact.get(phone_key)) or (f != 'phone' and not contact.get(f))]
            
            if missing_fields:
                errors.append({
                    "row": idx + 1,
                    "error": f"Missing required fields: {', '.join(missing_fields)}"
                })
                continue
            
            # Validate and normalize phone number format
            phone = str(contact.get(phone_key, '')).strip()
            # Remove parentheses, spaces, and dashes
            phone = "".join(filter(lambda x: x.isdigit() or x == '+', phone))
            
            if not phone.startswith('+'):
                # Heuristic: If it's long enough (e.g. 10-12 digits), prepend '+'
                if len(phone) >= 10:
                    phone = '+' + phone
                else:
                    errors.append({
                        "row": idx + 1,
                        "error": f"Invalid phone format '{phone}'. Must include country code."
                    })
                    continue
            
            # Update normalized phone back to contact
            contact[phone_key] = phone
            valid_contacts.append(contact)
        
        return {
            "valid": len(valid_contacts),
            "invalid": len(errors),
            "errors": errors[:10],  # Return first 10 errors
            "contacts": valid_contacts
        }
    
    async def get_campaign(self, campaign_id: UUID) -> Optional[Campaign]:
        """Get campaign by ID."""
        result = await self.db.execute(
            select(Campaign).where(Campaign.id == campaign_id)
        )
        return result.scalar_one_or_none()
    
    async def list_campaigns(
        self,
        company_id: UUID,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Campaign]:
        """
        List campaigns for a company.
        
        Args:
            company_id: Company UUID
            status: Filter by status
            limit: Max results
            offset: Pagination offset
            
        Returns:
            List of campaigns
        """
        query = select(Campaign).where(Campaign.company_id == company_id)
        
        if status:
            query = query.where(Campaign.status == status)
        
        query = query.order_by(Campaign.created_at.desc()).limit(limit).offset(offset)
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def update_campaign_status(
        self,
        campaign_id: UUID,
        status: str
    ):
        """
        Update campaign status.
        
        Args:
            campaign_id: Campaign UUID
            status: New status
        """
        updates = {"status": status, "updated_at": datetime.utcnow()}
        
        if status == "running":
            updates["started_at"] = datetime.utcnow()
        elif status == "completed":
            updates["completed_at"] = datetime.utcnow()
        
        await self.db.execute(
            update(Campaign)
            .where(Campaign.id == campaign_id)
            .values(**updates)
        )
        await self.db.commit()
        
        logger.info(f"Campaign {campaign_id} status updated to {status}")
    
    async def get_campaign_status(self, campaign_id: UUID) -> Dict[str, Any]:
        """
        Get real-time campaign status and metrics.
        
        Args:
            campaign_id: Campaign UUID
            
        Returns:
            Status dict with metrics
        """
        campaign = await self.get_campaign(campaign_id)
        
        if not campaign:
            return {}
        
        # Get call status counts
        result = await self.db.execute(
            select(
                CampaignCall.status,
                func.count(CampaignCall.id).label('count')
            )
            .where(CampaignCall.campaign_id == campaign_id)
            .group_by(CampaignCall.status)
        )
        
        status_counts = {row.status: row.count for row in result}
        
        return {
            "campaign_id": str(campaign_id),
            "name": campaign.name,
            "status": campaign.status,
            "total_contacts": campaign.total_contacts,
            "calls_initiated": campaign.calls_initiated,
            "calls_completed": campaign.calls_completed,
            "calls_failed": campaign.calls_failed,
            "pending": status_counts.get("pending", 0),
            "calling": status_counts.get("calling", 0),
            "completed": status_counts.get("completed", 0),
            "failed": status_counts.get("failed", 0),
            "started_at": campaign.started_at.isoformat() if campaign.started_at else None,
            "completed_at": campaign.completed_at.isoformat() if campaign.completed_at else None
        }
    
    async def get_active_calls(self, campaign_id: UUID) -> List[Dict[str, Any]]:
        """
        Get currently active calls for a campaign.
        
        Args:
            campaign_id: Campaign UUID
            
        Returns:
            List of active call dicts
        """
        result = await self.db.execute(
            select(CampaignCall)
            .where(
                CampaignCall.campaign_id == campaign_id,
                CampaignCall.status == "calling"
            )
            .order_by(CampaignCall.called_at.desc())
        )
        
        calls = result.scalars().all()
        
        return [
            {
                "id": str(call.id),
                "contact_name": call.contact_data.get("name", "Unknown"),
                "contact_phone": call.contact_data.get("phone"),
                "called_at": call.called_at.isoformat() if call.called_at else None,
                "duration": (datetime.utcnow() - call.called_at).seconds if call.called_at else 0
            }
            for call in calls
        ]
