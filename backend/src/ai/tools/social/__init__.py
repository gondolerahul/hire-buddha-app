"""
Social Media Tools — Base class and package exports.

Provides the abstract SocialMediaTool base class used by all
platform-specific tools (Phase 1, Phase 2, Phase 3).
"""
from src.ai.tools.social.base import SocialMediaTool

# --- Phase 1 ---
from src.ai.tools.social.linkedin import (
    LinkedInCreatePostTool,
    LinkedInGetAnalyticsTool,
    LinkedInManageCommentsTool,
    LinkedInGetProfileTool,
)
from src.ai.tools.social.twitter import (
    TwitterCreatePostTool,
    TwitterSearchTool,
    TwitterGetMentionsTool,
    TwitterGetAnalyticsTool,
)
from src.ai.tools.social.facebook import (
    FacebookCreatePostTool,
    FacebookGetInsightsTool,
    FacebookManageCommentsTool,
    FacebookSendMessageTool,
)
from src.ai.tools.social.instagram import (
    InstagramPublishMediaTool,
    InstagramGetInsightsTool,
    InstagramManageCommentsTool,
    InstagramDiscoverHashtagsTool,
)
from src.ai.tools.social.google_ads import (
    GoogleAdsCreateCampaignTool,
    GoogleAdsReportTool,
    GoogleAdsManageKeywordsTool,
    GoogleAdsGetAdGroupsTool,
)

# --- Phase 2 ---
from src.ai.tools.social.youtube import (
    YouTubeUploadVideoTool,
    YouTubeManagePlaylistsTool,
    YouTubeGetAnalyticsTool,
    YouTubeManageCommentsTool,
)
from src.ai.tools.social.tiktok import (
    TikTokPublishVideoTool,
    TikTokGetVideosTool,
    TikTokGetAnalyticsTool,
    TikTokManageCommentsTool,
)
from src.ai.tools.social.reddit import (
    RedditCreatePostTool,
    RedditSearchTool,
    RedditManageCommentsTool,
    RedditGetAnalyticsTool,
)
from src.ai.tools.social.quora import (
    QuoraSearchQuestionsTool,
    QuoraPostAnswerTool,
    QuoraGetSpacesTool,
    QuoraGetAnalyticsTool,
)
from src.ai.tools.social.pinterest import (
    PinterestCreatePinTool,
    PinterestManageBoardsTool,
    PinterestGetAnalyticsTool,
    PinterestSearchPinsTool,
)
from src.ai.tools.social.meta_ads import (
    MetaAdsCreateCampaignTool,
    MetaAdsManageAdsetsTool,
    MetaAdsReportTool,
    MetaAdsManageAudiencesTool,
)
from src.ai.tools.social.linkedin_ads import (
    LinkedInAdsCreateCampaignTool,
    LinkedInAdsManageCreativesTool,
    LinkedInAdsReportTool,
    LinkedInAdsManageAudiencesTool,
)

# --- Phase 3 ---
from src.ai.tools.social.linkedin_sales_nav import (
    LinkedInSalesSearchLeadsTool,
    LinkedInSalesGetLeadTool,
    LinkedInSalesSaveLeadTool,
    LinkedInSalesGetListsTool,
)
from src.ai.tools.social.youtube_ads import (
    YouTubeAdsCreateCampaignTool,
    YouTubeAdsManageAdGroupsTool,
    YouTubeAdsReportTool,
    YouTubeAdsManageTargetingTool,
)
from src.ai.tools.social.x_ads import (
    XAdsCreateCampaignTool,
    XAdsManageLineItemsTool,
    XAdsReportTool,
    XAdsManageAudiencesTool,
)
from src.ai.tools.social.snapchat_ads import (
    SnapchatAdsCreateCampaignTool,
    SnapchatAdsManageAdSquadsTool,
    SnapchatAdsReportTool,
    SnapchatAdsManageAudiencesTool,
)

__all__ = [
    "SocialMediaTool",
    # LinkedIn
    "LinkedInCreatePostTool", "LinkedInGetAnalyticsTool",
    "LinkedInManageCommentsTool", "LinkedInGetProfileTool",
    # Twitter/X
    "TwitterCreatePostTool", "TwitterSearchTool",
    "TwitterGetMentionsTool", "TwitterGetAnalyticsTool",
    # Facebook
    "FacebookCreatePostTool", "FacebookGetInsightsTool",
    "FacebookManageCommentsTool", "FacebookSendMessageTool",
    # Instagram
    "InstagramPublishMediaTool", "InstagramGetInsightsTool",
    "InstagramManageCommentsTool", "InstagramDiscoverHashtagsTool",
    # Google Ads
    "GoogleAdsCreateCampaignTool", "GoogleAdsReportTool",
    "GoogleAdsManageKeywordsTool", "GoogleAdsGetAdGroupsTool",
    # YouTube
    "YouTubeUploadVideoTool", "YouTubeManagePlaylistsTool",
    "YouTubeGetAnalyticsTool", "YouTubeManageCommentsTool",
    # TikTok
    "TikTokPublishVideoTool", "TikTokGetVideosTool",
    "TikTokGetAnalyticsTool", "TikTokManageCommentsTool",
    # Reddit
    "RedditCreatePostTool", "RedditSearchTool",
    "RedditManageCommentsTool", "RedditGetAnalyticsTool",
    # Quora
    "QuoraSearchQuestionsTool", "QuoraPostAnswerTool",
    "QuoraGetSpacesTool", "QuoraGetAnalyticsTool",
    # Pinterest
    "PinterestCreatePinTool", "PinterestManageBoardsTool",
    "PinterestGetAnalyticsTool", "PinterestSearchPinsTool",
    # Meta Ads
    "MetaAdsCreateCampaignTool", "MetaAdsManageAdsetsTool",
    "MetaAdsReportTool", "MetaAdsManageAudiencesTool",
    # LinkedIn Ads
    "LinkedInAdsCreateCampaignTool", "LinkedInAdsManageCreativesTool",
    "LinkedInAdsReportTool", "LinkedInAdsManageAudiencesTool",
    # LinkedIn Sales Navigator
    "LinkedInSalesSearchLeadsTool", "LinkedInSalesGetLeadTool",
    "LinkedInSalesSaveLeadTool", "LinkedInSalesGetListsTool",
    # YouTube Ads
    "YouTubeAdsCreateCampaignTool", "YouTubeAdsManageAdGroupsTool",
    "YouTubeAdsReportTool", "YouTubeAdsManageTargetingTool",
    # X Ads
    "XAdsCreateCampaignTool", "XAdsManageLineItemsTool",
    "XAdsReportTool", "XAdsManageAudiencesTool",
    # Snapchat Ads
    "SnapchatAdsCreateCampaignTool", "SnapchatAdsManageAdSquadsTool",
    "SnapchatAdsReportTool", "SnapchatAdsManageAudiencesTool",
]

