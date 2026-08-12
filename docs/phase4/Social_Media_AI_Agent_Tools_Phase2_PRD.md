# Social Media AI Agent Tools — Phase 2 PRD

## 1. Overview

This document defines the Phase 2 implementation for social media AI agent tools, expanding to additional platforms beyond the Phase 1 foundation (LinkedIn, X/Twitter, Facebook, Instagram, Google Ads).

Phase 2 covers **5 additional platforms** for organic content management and **2 advertising platforms**:
- **Organic**: YouTube, TikTok, Reddit, Quora, Pinterest
- **Advertising**: Meta Ads, LinkedIn Ads

## 2. Dependencies

Phase 2 builds on the Phase 1 foundation:
- `SocialConnection` model and `social_connections` table
- `SocialMediaTool` base class with credential resolution
- `social_connection_service.py` for token management
- Existing webhook strategy infrastructure

All Phase 1 infrastructure is reused — no new foundation work is needed.

---

## 3. Platform Specifications

### 3.1 YouTube (Organic)

**API**: YouTube Data API v3 (`https://www.googleapis.com/youtube/v3`)
**Auth**: OAuth 2.0 (same Google OAuth as Google Ads, different scopes)
**Scopes**: `youtube.upload`, `youtube.readonly`, `youtube.force-ssl`

| Tool Name | Description | Key API Endpoints |
|---|---|---|
| `youtube_upload_video` | Upload videos with title, description, tags, category | `POST /videos?uploadType=resumable` |
| `youtube_manage_playlists` | Create/update/delete playlists and add/remove videos | `POST/PUT/DELETE /playlists`, `POST/DELETE /playlistItems` |
| `youtube_get_analytics` | Channel and video-level analytics (views, watch time, CTR, audience) | YouTube Analytics API `GET /reports` |
| `youtube_manage_comments` | List, reply, moderate comments on videos | `GET/POST/DELETE /commentThreads`, `PUT /comments` |

**Rate Limits**: 10,000 quota units/day default. Video upload = 1,600 units. Reads = 1-3 units.

---

### 3.2 TikTok (Organic)

**API**: TikTok Content Posting API v2 (`https://open.tiktokapis.com/v2`)
**Auth**: OAuth 2.0 with PKCE
**Scopes**: `video.upload`, `video.list`, `user.info.basic`

| Tool Name | Description | Key API Endpoints |
|---|---|---|
| `tiktok_publish_video` | Upload and publish videos (direct or share URL) | `POST /post/publish/video/init/`, `POST /post/publish/content/init/` |
| `tiktok_get_videos` | List creator's published videos | `POST /video/list/` |
| `tiktok_get_analytics` | Video and account performance metrics | `GET /research/user/info/`, video insights |
| `tiktok_manage_comments` | List and reply to comments on videos | `POST /comment/list/`, `POST /comment/reply/` |

**Rate Limits**: Varies by endpoint; 600 RPM for content posting, 1,000 RPM for queries.

---

### 3.3 Reddit (Organic)

**API**: Reddit API (`https://oauth.reddit.com`)
**Auth**: OAuth 2.0 (script or web app type)
**Scopes**: `submit`, `read`, `identity`, `edit`, `history`

| Tool Name | Description | Key API Endpoints |
|---|---|---|
| `reddit_create_post` | Submit text posts, link posts, or image/video posts to subreddits | `POST /api/submit` |
| `reddit_search` | Search posts across Reddit or within specific subreddits | `GET /search`, `GET /r/{subreddit}/search` |
| `reddit_manage_comments` | Reply to posts/comments, edit/delete own comments | `POST /api/comment`, `POST /api/editusertext` |
| `reddit_get_analytics` | Get karma, post scores, upvote ratios, comment counts | `GET /user/{username}/about`, `GET /api/info` |

**Rate Limits**: 100 queries/minute per OAuth client. 10 posts/minute for submissions.

---

### 3.4 Quora (Organic)

**API**: Quora Partner API (limited availability) / Quora Ads API
**Auth**: API Key-based (Partner API) or OAuth 2.0 (Ads)
**Note**: Quora's public writing API is limited; tool focuses on content discovery and Spaces.

| Tool Name | Description | Key API Endpoints |
|---|---|---|
| `quora_search_questions` | Search questions by topic or keyword for content ideation | Partner API search endpoints |
| `quora_post_answer` | Draft and post answers to specific questions (if API access granted) | Partner API answer submission |
| `quora_get_spaces` | List and manage Quora Spaces for content distribution | Spaces management endpoints |
| `quora_get_analytics` | View counts, upvotes, shares for answers and Spaces | Analytics endpoints |

**Rate Limits**: 1,000 requests/day (Partner API tier).

---

### 3.5 Pinterest (Organic)

**API**: Pinterest API v5 (`https://api.pinterest.com/v5`)
**Auth**: OAuth 2.0
**Scopes**: `boards:read`, `boards:write`, `pins:read`, `pins:write`

| Tool Name | Description | Key API Endpoints |
|---|---|---|
| `pinterest_create_pin` | Create image or video pins with title, description, link, and board | `POST /pins` |
| `pinterest_manage_boards` | Create/update/delete boards and sections | `POST/PATCH/DELETE /boards`, `/board_sections` |
| `pinterest_get_analytics` | Pin and account-level analytics (impressions, saves, clicks) | `GET /user_account/analytics`, `GET /pins/{id}/analytics` |
| `pinterest_search_pins` | Search public pins by keyword for content inspiration | `GET /search/pins` |

**Rate Limits**: 1,000 writes/hour, 200 reads/second per user token.

---

### 3.6 Meta Ads (Advertising)

**API**: Meta Marketing API v22.0 (`https://graph.facebook.com/v22.0`)
**Auth**: OAuth 2.0 (same as Facebook, requires `ads_management` scope)
**Levels**: Campaign → Ad Set → Ad (hierarchical structure)

| Tool Name | Description | Key API Endpoints |
|---|---|---|
| `meta_ads_create_campaign` | Create campaign with objective (AWARENESS, TRAFFIC, CONVERSIONS, etc.) | `POST /act_{ad_account_id}/campaigns` |
| `meta_ads_manage_adsets` | Create/update ad sets with targeting, budget, schedule | `POST/PUT /act_{ad_account_id}/adsets` |
| `meta_ads_report` | Fetch campaign/ad set/ad performance metrics with breakdowns | `GET /act_{ad_account_id}/insights` |
| `meta_ads_manage_audiences` | Create/update Custom and Lookalike audiences | `POST /act_{ad_account_id}/customaudiences` |

**Rate Limits**: Tiered based on ad spend level. Standard: 200 calls/hour per ad account.

---

### 3.7 LinkedIn Ads (Advertising)

**API**: LinkedIn Campaign Manager API (`https://api.linkedin.com/rest`)
**Auth**: OAuth 2.0 (requires `r_ads`, `rw_ads` scopes)
**Levels**: Account → Campaign Group → Campaign → Creative

| Tool Name | Description | Key API Endpoints |
|---|---|---|
| `linkedin_ads_create_campaign` | Create Sponsored Content, Message Ads, or Dynamic Ads campaigns | `POST /adCampaigns` |
| `linkedin_ads_manage_creatives` | Create/update ad creatives with copy, media, and CTAs | `POST /adCreatives` |
| `linkedin_ads_report` | Fetch campaign analytics with demographic/company breakdowns | `GET /adAnalytics` |
| `linkedin_ads_manage_audiences` | Create/update matched audiences (company, contact, retargeting) | `POST /dmpSegments` |

**Rate Limits**: 100 calls/day per application for analytics; 80,000 calls/day for management.

---

## 4. Implementation Architecture

### 4.1 File Structure (New Files)

```
backend/src/ai/tools/social/
├── youtube.py          # 4 YouTube tools
├── tiktok.py           # 4 TikTok tools
├── reddit.py           # 4 Reddit tools
├── quora.py            # 4 Quora tools
├── pinterest.py        # 4 Pinterest tools
├── meta_ads.py         # 4 Meta Ads tools
└── linkedin_ads.py     # 4 LinkedIn Ads tools
```

### 4.2 Tool Naming Convention

Pattern: `{platform}_{action}` (consistent with Phase 1)

Examples: `youtube_upload_video`, `reddit_create_post`, `meta_ads_report`

### 4.3 Credential Requirements

| Platform | Auth Type | Key Metadata |
|---|---|---|
| YouTube | OAuth 2.0 | Uses Google OAuth (shared with Google Ads) |
| TikTok | OAuth 2.0 + PKCE | `app_id`, `app_secret` in oauth_metadata |
| Reddit | OAuth 2.0 | `client_id`, `client_secret`, `user_agent` |
| Quora | API Key | `api_key` in oauth_metadata |
| Pinterest | OAuth 2.0 | Standard OAuth flow |
| Meta Ads | OAuth 2.0 | `ad_account_id` in oauth_metadata |
| LinkedIn Ads | OAuth 2.0 | `ad_account_id` in oauth_metadata |

### 4.4 Webhook Strategies (New)

| Strategy | Detection | Source |
|---|---|---|
| `YouTubeWebhookStrategy` | YouTube PubSubHubbub notifications | `youtube` |
| `PinterestWebhookStrategy` | Pinterest webhook headers | `pinterest` |

Reddit, Quora, and TikTok do not provide webhook push notifications—polling is recommended instead.

---

## 5. Acceptance Criteria

1. All 28 new tools register in `ToolRegistry` and return valid function schemas
2. Each tool correctly resolves credentials from `social_connections` via `SocialMediaTool._resolve_credentials()`
3. Webhook strategies for YouTube and Pinterest detect their respective events before `GenericWebhookStrategy`
4. All existing Phase 1 tests continue to pass
5. New E2E tests achieve ≥95% coverage of tool schemas and error paths

## 6. Estimated Effort

| Component | Tools | Estimate |
|---|---|---|
| YouTube | 4 | 3 hours |
| TikTok | 4 | 3 hours |
| Reddit | 4 | 2 hours |
| Quora | 4 | 2 hours |
| Pinterest | 4 | 2 hours |
| Meta Ads | 4 | 4 hours |
| LinkedIn Ads | 4 | 3 hours |
| Integration + Tests | — | 3 hours |
| **Total** | **28** | **~22 hours** |

## 7. Phase 3 (Future)

Phase 3 will cover advanced integrations:
- **LinkedIn Sales Navigator**: Advanced prospecting and lead management tools
- **YouTube Ads**: Video campaign management via Google Ads API
- **X Ads**: Twitter/X advertising campaign management
- **Snapchat Ads**: Snap ad campaign management (if requested)
