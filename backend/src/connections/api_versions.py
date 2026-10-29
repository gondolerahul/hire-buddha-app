"""Provider API versions that lapse (LI-E1, GADS-E2): one setting each, and a
warning at start-up before the provider retires the version in use.

LinkedIn names a version by its month (``YYYYMM``) and sunsets it about a year
later, so the warning comes past ten months. Google Ads numbers its versions;
the sunset month Google announces is a setting beside the version, and the
warning comes 60 days before it. A call with a retired version fails, which is
what happened to LinkedIn's 202409 and 202509.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import List, Optional

logger = logging.getLogger(__name__)

LINKEDIN_WARN_MONTHS = 10
GOOGLE_ADS_WARN_DAYS = 60


def linkedin_version() -> str:
    from src.common.config import settings

    return settings.LINKEDIN_API_VERSION


def google_ads_version() -> str:
    from src.common.config import settings

    return settings.GOOGLE_ADS_API_VERSION


def _month(value: str, fmt: str) -> Optional[date]:
    try:
        return datetime.strptime(str(value), fmt).date()
    except (TypeError, ValueError):
        return None


def stale(today: Optional[date] = None) -> List[str]:
    """What to tell the operator: each version setting near or past its end."""
    from src.common.config import settings

    today = today or datetime.utcnow().date()
    found: List[str] = []
    released = _month(settings.LINKEDIN_API_VERSION, "%Y%m")
    if released is None:
        found.append(f"LINKEDIN_API_VERSION {settings.LINKEDIN_API_VERSION!r} is not a YYYYMM version")
    else:
        age = (today.year - released.year) * 12 + today.month - released.month
        if age > LINKEDIN_WARN_MONTHS:
            found.append(f"LINKEDIN_API_VERSION {settings.LINKEDIN_API_VERSION} is {age} months old: LinkedIn "
                         "sunsets a version about a year after release, so move to a current one")
    sunset = _month(settings.GOOGLE_ADS_API_SUNSET, "%Y-%m")
    if sunset is None:
        found.append(f"GOOGLE_ADS_API_SUNSET {settings.GOOGLE_ADS_API_SUNSET!r} is not a YYYY-MM month")
    elif (sunset - today).days <= GOOGLE_ADS_WARN_DAYS:
        found.append(f"GOOGLE_ADS_API_VERSION {settings.GOOGLE_ADS_API_VERSION} is sunset in "
                     f"{settings.GOOGLE_ADS_API_SUNSET}: move to a current version and its sunset month")
    return found


def warn_if_stale() -> List[str]:
    """Log :func:`stale`'s findings (the API's start-up); returns them."""
    found = stale()
    for message in found:
        logger.warning(message)
    return found
