"""
Social platform tools.

One registered tool, ``social_api`` (``social_api.py``); each platform module
holds its operations as ``SocialMediaTool`` subclasses, which are not
registered as tools (P6.2).
"""
from src.ai.tools.social.base import SocialMediaTool
from src.ai.tools.social.social_api import SOCIAL_PLATFORMS, SocialAPITool

__all__ = ["SOCIAL_PLATFORMS", "SocialAPITool", "SocialMediaTool"]
