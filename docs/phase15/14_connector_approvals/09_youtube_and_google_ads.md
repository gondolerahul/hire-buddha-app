# 09 — YouTube and Google Ads: publishing, analytics, ads and ad performance

> **Researched:** 2026-10-28 · **Status:** Not started. There is no connector for either service. The tools exist (`ai/tools/social/youtube.py`, `google_ads.py`), but they read the old `social_connections` table, which needs each business's own Google app and tokens and is dropped one release after the WS7 cutover (`connections/migrate.py`). No screen connects either service today.
> **App:** a third Google Cloud project, `hirebuddha-marketing`, for both services (§4). The provider guide doesn't cover it yet; §6 A lists the setup.
> **Lead time:** brand and sensitive-scope verification take about two weeks. YouTube's audit, needed for more than 100 uploads a day, has no published timeline (plan on weeks). Google Ads Explorer access is usually granted automatically, and Basic access is reviewed within minutes of brand verification; Standard access is a manual review. **Cost:** free (quota only). Ad spend is the business's own, billed by Google to its Google Ads account.

---

## 1. What the automation is made of

| Job | Google service | What HireBuddha calls | What it needs from Google |
|---|---|---|---|
| Publish videos: upload, schedule, thumbnails, playlists, captions | YouTube Data API v3 | `videos.insert` (resumable), `thumbnails.set`, `playlists`, `playlistItems`, `captions` | OAuth verification (sensitive scopes); YouTube's compliance audit for more than 100 uploads a day (§3.2) |
| Answer and moderate comments | YouTube Data API v3 | `commentThreads.list`, `comments.insert`, `comments.setModerationStatus` | The same, and a person approves each reply (§2) |
| Channel and video analytics | YouTube Analytics API (queries) and YouTube Reporting API (daily bulk reports) | `reports.query`; reporting jobs | OAuth verification |
| Revenue from ads shown on the business's own videos (channels in the YouTube Partner Program only) | YouTube Analytics API with the monetary scope | Revenue, ad impressions, CPM and similar metrics | Verification of `yt-analytics-monetary.readonly`; ask only if a business wants it |
| Run ads on YouTube | **Google Ads API** | **Demand Gen** campaigns (video ads on YouTube in-stream, in-feed and Shorts, plus Discover and Gmail) and Performance Max (YouTube is one of its channels). Ad videos come from the channel, or are uploaded through Google Ads' `YouTubeVideoUploadService` | Verification of `adwords`; the project's Google Ads API access level (§3.3) |
| Ad performance | Google Ads API reports (GAQL); for views that came from ads, YouTube Analytics' `ADVERTISING` traffic source | `googleAds:searchStream` | The same |

**Video campaigns can't be created through the API.** Google's guide says the Google Ads API mostly reads and reports Video campaigns; from v24 it can only change their responsive video ads. For new YouTube ads it points to **Demand Gen**, which the API supports fully, for creation and for management. Video reach and view campaigns stay in the Google Ads interface (or Google Ads scripts), and HireBuddha reports on them.

## 2. YouTube's rules that bind an AI agent product

From the [YouTube API Services Developer Policies](https://developers.google.com/youtube/terms/developer-policies) and the [Required Minimum Functionality](https://developers.google.com/youtube/terms/required-minimum-functionality), with their section numbers.

| Rule | What it means for HireBuddha | Requirement |
|---|---|---|
| Actions that insert, update or delete content are identified, and the person expressly consents **before** each one runs. Uploads, comments and likes are never automated without the person's prior, specific consent (III.E.3.d, III.I.2) | A person approves each upload, metadata change, playlist change, comment reply and moderation. The approval screen shows exactly what will be published | SH-E4, YT-E3 |
| The person keeps final control: don't change values they gave without consent, and don't change a video's visibility unless they asked (III.C.3, III.E.3.f) | Agents propose; the approval screen is where the person edits. The person sets the privacy status | YT-E2 |
| Upload clients let the person set the title (up to 100 characters), the description (up to 5,000 bytes) and the privacy status (public, private, unlisted) | Every upload approval shows and lets the person edit these three | YT-E2 |
| Comment replies show the comment being answered, the channel name, the video title, and the account the reply will post as (Required Minimum Functionality) | The reply approval shows all four | YT-E3 |
| Each upload says whether the video is made for kids (`status.selfDeclaredMadeForKids`), and realistic altered or synthetic content is disclosed (`status.containsSyntheticMedia`). YouTube labels undisclosed synthetic content itself and penalises creators who keep failing to disclose it | AI-made videos are flagged; the person confirms the audience | YT-E2 |
| **Storage limits.** Tokens may be kept as long as needed. Analytics data may be kept, but every 30 days the client must confirm the person's authorisation still holds. Other data from the person's account may be kept for at most 30 days unless refreshed, and so may public data about other channels. Delete within 7 days of a revocation in HireBuddha (30 days when the person revokes on Google's security settings page), and honour deletion requests within 7 days (III.D.2, III.E.4) | YouTube data in traces, memory and records follows these limits | SH-E2, SH-E1, YT-E5 |
| No copies of YouTube audio or video without YouTube's written approval (III.E.1) | Don't download YouTube videos into storage, for example to have a model watch them. Work from the business's own source file or the YouTube URL | YT-E5 |
| Metrics: no YouTube numbers replaced by independently calculated ones, no derived metrics passed off as YouTube's, non-YouTube metrics clearly labelled when shown next to YouTube's, and data of different content owners never combined (III.E.2, III.E.4.h) | Dashboards label each number's source. No YouTube benchmarks across businesses (the same line as GOOG-E6) | YT-E6 |
| Terms and privacy: HireBuddha's terms say users agree to the YouTube Terms of Service, and the privacy policy says HireBuddha uses YouTube API Services, links the Google Privacy Policy, explains what YouTube data it uses and how, and how to revoke access on Google's security settings page (III.A.1, III.A.2) | Statements in SH-07 and SH-08 | §5 of [00](00_shared_prerequisites.md) |
| **Exactly one API project per API client** (III.D.1.c). Extra quota is used only for the approved use case (III.D.3), and access can be cut after 90 days without use (III.D.4) | Dev and production share the YouTube project (§4). Never add a project to get more quota | YT-04, YT-21 |
| YouTube may audit at any time and ask for accounts to test (III.H) | Keep the reviewer business of SH-14 working | SH-14 |

## 3. What Google checks

### 3.1 OAuth verification of the scopes

YouTube's scopes and Google Ads' `adwords` scope are **sensitive**: brand verification, a justification per scope and a demo video, but no CASA assessment (none is restricted). Google's help lists about 10 business days for a sensitive-scope review. Until the app is verified, people see *Google hasn't verified this app*, and only 100 users can connect.

Ask for the narrowest scope each feature needs, and add scopes only when their features ship:

| Feature | Scope | Note |
|---|---|---|
| Upload videos (scheduled or not) and set thumbnails | `youtube.upload` | The narrowest scope that uploads |
| Show the channel's videos, playlists and comments | `youtube.readonly` | Read only |
| Playlists, comment replies and moderation, captions, editing a video after upload | `youtube.force-ssl` | Manages the whole channel. Request it only when these features ship, with its own justification |
| Channel and video analytics | `yt-analytics.readonly` | — |
| Revenue analytics | `yt-analytics-monetary.readonly` | Only for businesses in the YouTube Partner Program that ask for it |
| Google Ads | `adwords` | Google Ads has only this one scope |

### 3.2 YouTube quota and the compliance audit

* **Default quota per project** (Oct 2026): 100 `videos.insert` calls a day, 100 `search.list` calls a day, and 10,000 units a day for all other methods. **Every business shares the project's quota**, so HireBuddha as a whole can upload 100 videos a day.
* More quota needs YouTube's **API compliance audit**: the [Audit and Quota Extension Form](https://support.google.com/youtube/contact/yt_api_form). YouTube's API Services team checks the use case against the policies of §2. No timeline is published. YouTube audits again from time to time, offers an appeals form after a failed audit, and has a change-of-control form for corporate transactions.
* Google's reference now says uploads from unverified projects **are not** restricted to private viewing. Many older guides and forum answers still describe the 2020 rule that locked them private. A video can still default to private because of the channel's own settings.

### 3.3 Google Ads API access (changed on 9 September 2026)

**Developer tokens are retired.** Since 9 September 2026, access belongs to the **Google Cloud project that owns the OAuth client**. A `developer-token` header is ignored, and no Google Ads manager account is needed. The access level, and its daily allowance, is shared by every business using the project.

| Level | Accounts | Operations a day | How to get it |
|---|---|---|---|
| Test | Test accounts only (they serve no ads) | 15,000 | Automatic when the API is enabled in the project |
| Explorer | Test and production | 2,880 on production accounts | Apply on the project's *Google Ads API* page in Cloud Console; usually approved automatically. Account creation, user management, planning and billing services are not allowed |
| Basic | Test and production | 15,000 | Needs the project's **brand verification** with no warnings, and a **paid billing account** (applications from free-trial projects are refused). Reviewed within minutes |
| Standard | Test and production | Unlimited | A manual review of the tool: its features and audience, demo sign-in for external users, and the Required Minimum Functionality |

The **Required Minimum Functionality** (RMF) applies only at Standard. A tool that creates, manages and reports campaigns for other businesses, as HireBuddha does, is a full-service tool. For that, RMF asks for: campaign and ad-group creation, budgets, keywords, negative keywords, match types, location and language targeting, conversion tracking, callouts, the Target CPA, Target ROAS and Maximise Conversions bidding options, and the standard reports. Google's compliance team may instead class a tool limited to certain campaign types as a *limited* tool.

### 3.4 What each business needs (Google doesn't review these for us, but they block the business)

* **YouTube:** a channel, phone-verified for videos over 15 minutes and for custom thumbnails (YouTube's *intermediate features*; thumbnails can take up to a day after verification). The channel has its own daily upload limit (`uploadLimitExceeded`).
* **Google Ads:** an account with billing, and advertiser verification when Google asks for it. Ads use public or unlisted YouTube videos. Linking the channel to the Ads account (in YouTube Studio or Google Ads) adds earned actions and audiences. Through the API, `DataLinkService` can ask a creator to link a video, and the creator must accept.
* **Ad policies:** Google Ads policies apply to every ad an AI employee drafts. The person who approves an ad answers for it (SH-08).
* **Google's third-party policy** applies when HireBuddha or a partner runs a business's Google Ads *as a service*: fees disclosed in writing, a monthly report of cost, clicks and impressions, and the customer ID on request.

## 4. Decisions

1. **A separate Google Cloud project, `hirebuddha-marketing`, for YouTube and Google Ads**, with its own OAuth client and Google Ads API access.
   * *Why:* the Gmail project's restricted-scope review and CASA ([02](02_google.md)) take months, while YouTube's and Ads' scopes are only sensitive and can pass in about two weeks on their own. YouTube's audit and the Ads access level both belong to a project, so a project with one purpose is simpler to audit.
   * *One project for dev and production:* YouTube allows exactly one project per API client (III.D.1.c), so the dev environment adds its own OAuth client or redirect URI to this project. There is no second YouTube project.
   * *Cost:* one more brand verification, with the same name, logo and domain.
2. **Two connectors on that project**: `youtube_channel` (the account is a channel) and `google_ads` (the account is a Google Ads customer the person can reach, chosen after consent). Each asks only for its own scopes. The existing tools switch to the connectors' credentials (`connections/client.py` `PLATFORM_CONNECTORS`).
3. **Publishing and analytics first, ads second.** Publishing and analytics need only sensitive scopes and fit the default quota for a pilot. Ads need Basic access and the spending approvals of GADS-E4.

## 5. Found in the code

| Finding | Where | Fix |
|---|---|---|
| No connectors. The tools read `social_connections`, which needs each business's own Google app and tokens, and that table is dropped after WS7. Nothing in the frontend connects YouTube or Google Ads | `ai/tools/social/youtube.py`, `google_ads.py`, `connections/client.py`, `connections/migrate.py` | YT-E1, GADS-E1 |
| Google Ads API **v18**, which was sunset in 2025. v23 to v26 are current; v26 sunsets about November 2027, and from v26 Google releases twice a month, with four major versions a year | `google_ads.py` `GOOGLE_ADS_API_BASE` | GADS-E2 |
| Reads a per-connection `developer_token` and sends the `developer-token` header, which Google no longer uses | `google_ads.py` | GADS-E1 |
| Offers to create `VIDEO` campaigns, which the API can't do. Creates a campaign with no ad groups, ads or targeting. `MANUAL_CPC` switches on Enhanced CPC, which Google retired for Search and Display in March 2025 | `GoogleAdsCreateCampaignTool` | GADS-E3 |
| Keyword and bid changes run without a person's approval. Campaigns start paused (keep that), but nothing stops a later enable or budget increase | `GoogleAdsManageKeywordsTool`, SH-E4 | GADS-E4 |
| No `login-customer-id`, which businesses and partners working through a manager account need | `google_ads.py` | GADS-E1 |
| Upload sets no `selfDeclaredMadeForKids` or `containsSyntheticMedia`, and has no scheduled publishing (`publishAt`). It downloads the video from a URL and holds all of it in memory (256 MB at most) | `YouTubeUploadVideoTool` | YT-E2, YT-E4 |
| Analytics defaults to 2024-01-01 to 2024-12-31, although its description promises the last 30 days. It has no dimensions (day, video, traffic source) | `YouTubeGetAnalyticsTool` | YT-E6 |
| Moderation sends `PUT …/comments/setModerationStatus`. YouTube's method is a `POST`, so moderation fails | `YouTubeManageCommentsTool` | YT-E3 |
| YouTube's WebSub notifications are checked (`X-Hub-Signature`) and become `youtube.video.published` events. Keep this | `gateway/webhook_inbound.py`, `gateway/webhook_signatures.py` | — |

## 6. Requirements

### A. The project (for both services)

| ID | Requirement | Owner | Done when | Status |
|----|-------------|-------|-----------|--------|
| YT-01 | Create `hirebuddha-marketing` under the company's Google Cloud organisation, on a **paid** billing account (Google Ads refuses access to free-trial projects). Enable the YouTube Data API v3, YouTube Analytics API, YouTube Reporting API and Google Ads API | Owner | — | Open |
| YT-02 | Brand verification as for Gmail (GOOG-02, GOOG-03): name `HireBuddha`, logo, support e-mail, homepage, privacy policy and terms, with `hirebuddha.com` verified by a project owner | Owner | Branding verified | Open |
| YT-03 | Two project owners; the developer contact is a group address read every day (GOOG-05) | Owner | — | Open |
| YT-04 | OAuth clients for production and dev in this one project, with the SH-12 redirect URIs. Client secrets go to Key Vault (`oauth-google-marketing-client-secret`) | Owner | Client IDs handed to engineering | Open |
| YT-05 | *Data access* lists only the scopes of the features that ship (§3.1). Start with `youtube.upload`, `youtube.readonly`, `yt-analytics.readonly` and `adwords` | Owner | — | Open |
| YT-06 | Reviewer and test assets (SH-16): a phone-verified YouTube channel with a few real videos; a Google Ads account with billing, a linked channel and a small budget for the demo; a Google Ads test account for engineering | Owner | Credentials in the vault | Open |

### B. Engineering: YouTube

| ID | Requirement | Where | Done when | Status |
|----|-------------|-------|-----------|--------|
| YT-E1 | **`youtube_channel` connector.** A catalog entry, and a Google provider entry for the marketing project's client. The account is the channel (`channels.list?mine=true`). Actions: upload, edit details, thumbnail, playlists, reply to comments, moderate, read analytics. Events: `youtube.video.published` (WebSub). Add `youtube` to `PLATFORM_CONNECTORS` so the tools use the connector's token | `connections/catalog/`, `connections/providers/oauth.py`, `connections/client.py` | A channel connects on dev and an agent uploads to it | Done (code) |
| YT-E2 | **Upload contract**: title, description and privacy status chosen by the person (default private); `selfDeclaredMadeForKids` required; `containsSyntheticMedia` set for realistic AI-made or altered video (on by default for videos HireBuddha's tools produced); `publishAt` for scheduling; category and tags. Never change an existing video's visibility unless the person asked | `ai/tools/social/youtube.py`, approval UI | A test: an upload without an audience choice is refused | Done (code) |
| YT-E3 | **Approvals** (SH-E4) for uploads, edits, playlist changes, replies and moderation. The approval shows exactly what goes out; for a reply, also the comment answered, the channel name, the video title and the account the reply posts as. Fix moderation (`POST`). For other people's comments, use moderation (`rejected`) | `ai/tools/social/youtube.py`, `ai/governance/hitl_gate.py` | No YouTube write runs without an approval | Done (code) |
| YT-E4 | **Uploads at size and at scale**: stream from the business's storage with chunked resumable uploads (no 256 MB limit in memory), resume after a failure, report processing status. Clear errors for `quotaExceeded` and `uploadLimitExceeded`. A per-business daily upload cap, so that one business can't use up the shared 100 a day | `ai/tools/social/youtube.py`, tenant storage | A 1 GB upload completes on dev | Done (code); the 1 GB test on dev is open |
| YT-E5 | **YouTube's data rules** (SH-E2): YouTube data in traces, memory and records deleted or refreshed within 30 days; analytics kept only while a check every 30 days confirms the token still works; on disconnect, revoke and delete within 7 days; no copies of videos | Retention job, `connections/service.py` | SH-E2's test with a YouTube comment | Done (code) |
| YT-E6 | **Analytics that answer questions**: dates computed (last 28 days by default); dimensions such as day, video, traffic source (including `ADVERTISING`), country and device; Reporting API jobs for daily bulk data. Any number HireBuddha computes is labelled as HireBuddha's, not YouTube's. No YouTube comparisons across businesses | `ai/tools/social/youtube.py` | An agent reports one video's last 28 days by traffic source | Done (code) |

### C. Engineering: Google Ads

| ID | Requirement | Where | Done when | Status |
|----|-------------|-------|-----------|--------|
| GADS-E1 | **`google_ads` connector** on the marketing project: scope `adwords`. After consent, list `customers:listAccessibleCustomers` and let the person choose the account, and the manager account if they work through one (sent as `login-customer-id`). Drop the per-connection developer token. Add `google_ads` to `PLATFORM_CONNECTORS` | `connections/catalog/`, `connections/providers/oauth.py`, `ai/tools/social/google_ads.py` | An agent reads campaigns of a test account on dev | Done (code) |
| GADS-E2 | **One Google Ads API version setting**, at a current major version, with a staleness warning like LI-E1's (four major versions a year, each lasting about a year). Update GAQL field names to that version (video metrics are now `metrics.video_trueview_views`, `metrics.video_trueview_view_rate` and `metrics.trueview_average_cpv`) | `ai/tools/social/google_ads.py`, `common/config.py` | Calls succeed on the current version | Done (code) |
| GADS-E3 | **YouTube ads through Demand Gen**: campaign, ad group, audience, location and language targeting, and the video responsive ad (video, headlines, descriptions, business name, logo, call to action). The video comes from the channel, or is uploaded with `YouTubeVideoUploadService`, which from v26 records whether the content is AI-generated. Performance Max with YouTube video assets later. Remove `VIDEO` creation (report on Video campaigns only) and Enhanced CPC | `ai/tools/social/google_ads.py` | A paused Demand Gen campaign with a video ad is created on a test account | Done (code); the test-account check is open |
| GADS-E4 | **Spending safety** (SH-E4): everything is created paused. Enabling a campaign, raising a budget or a bid, or adding broad-match keywords each needs a person's approval that shows the amount and its monthly effect. A monthly ceiling per business that HireBuddha never exceeds | `ai/tools/social/google_ads.py`, `ai/governance/hitl_gate.py` | A test: an enable without approval is refused | Partly done (code) |
| GADS-E5 | **Performance reports**: GAQL templates for campaign, ad group, ad, video and Demand Gen performance (impressions, views, view rate, CPV, clicks, cost, conversions, conversion value), next to YouTube Analytics' views from ads, each number labelled with its source (YT-E6). Costs in the account's currency | `ai/tools/social/google_ads.py` | An agent reports last week's YouTube ad results | Done (code); the test-account check is open |
| GADS-E6 | **Limits**: back off on `RESOURCE_EXHAUSTED`; count operations per business against the project's daily allowance (15,000 on Basic, shared by all businesses); report `CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION` as a setup error, not a tool failure | `ai/tools/social/google_ads.py` | — | Done (code) |

### D. Submissions

| ID | Requirement | Owner | Done when | Status |
|----|-------------|-------|-----------|--------|
| YT-10 | Brand verification of the marketing project (YT-02) | Owner | Verified | Open |
| YT-11 | **Sensitive-scope verification** of the YT-05 scopes: the justifications and the demo video of §7 | Owner + Eng | Approved | Open |
| GADS-10 | **Google Ads API access**: apply for Explorer, then Basic once YT-10 has passed and billing is paid, on the project's *Google Ads API* page in Cloud Console | Owner | Basic shown on that page | Open |
| YT-12 | **YouTube audit and quota extension**, before the pilot outgrows 100 uploads a day and in any case before general availability. Answers in §7. Reply to YouTube's API Services team within a day | Owner | Quota granted | Open |
| GADS-11 | **Standard access**, when 15,000 operations a day is no longer enough: RMF, or the case for a limited tool; demo sign-in. Google's compliance team writes to the project's owners | Owner + Eng | Standard shown | Open |

### E. After approval

| ID | Requirement | Owner | Done when | Status |
|----|-------------|-------|-----------|--------|
| YT-20 | Connectors to *Preview*, then *Available*; approvals recorded on *Platform Console → Connectors* | Eng | Catalog rows `approved` | Open |
| YT-21 | **YouTube's periodic audits**: answer within the deadline, resubmit the form if the use case changes (III.D.3), and never leave the project unused for 90 days | Owner | — | Open |
| GADS-20 | Upgrade the Google Ads API version on a calendar (GADS-E2), and follow the Google Ads developer blog | Eng | — | Open |
| GADS-21 | If HireBuddha or a partner runs a business's Google Ads as a service: Google's third-party policy (§3.4) | Owner | — | Open |

## 7. What to submit

**Justifications** (drafts):

> **`youtube.upload`:** HireBuddha's AI employees prepare videos for a business's own YouTube channel. The person connects the channel, reviews the title, description, thumbnail, audience, AI-content disclosure and privacy setting on HireBuddha's approval screen, and only then does HireBuddha upload the video, or schedule it, to that channel. This is the narrowest scope that can upload videos and set thumbnails. HireBuddha never deletes videos.

> **`youtube.readonly`:** shows the person their channel, videos and playlists in HireBuddha, so they can choose where a video goes and which comments to answer.

> **`yt-analytics.readonly`:** reports the channel's views, watch time and audience to the business in HireBuddha, and shows how each video performed after it was published.

> **`adwords`:** HireBuddha's AI employees draft YouTube ad campaigns (Demand Gen) in the business's own Google Ads account and report their results. Every campaign is created paused; turning it on or changing a budget needs a person's approval in HireBuddha. Google Ads has no narrower scope.

**Demo video** (YouTube, *Unlisted*, English, production client, one take of about 5 minutes, with captions naming the scope in use):

1. HireBuddha in the browser on the production hostname, signed in as the reviewer business.
2. *Connections → YouTube → Connect*: the in-app disclosure (SH-13), then Google's consent screen in English showing `HireBuddha` and the scopes. Zoom in on `client_id=` in the address bar.
3. The channel appears in *Connections*.
4. An AI employee prepares a video. The approval screen shows the title, description, thumbnail, privacy (*Private*), audience (*Not made for kids*) and *Altered or synthetic content: Yes*. *Approve*, then YouTube Studio shows the video with those settings (`youtube.upload`).
5. The channel's last 28 days in HireBuddha (`yt-analytics.readonly`), and its playlists (`youtube.readonly`).
6. *Connections → Google Ads → Connect*: the second consent screen (`adwords`); choose the account.
7. The AI employee drafts a Demand Gen campaign with the new video. It is created paused, and the approval shows the daily budget. *Approve*, then the Google Ads interface shows the campaign enabled, and HireBuddha shows its performance report.
8. *Disconnect* both: the Google Account's *Third-party access* page no longer lists HireBuddha.

**YouTube audit form (YT-12)**: say what HireBuddha is and give its production URL; name the APIs and methods it uses; describe the use case (each business connects its own channel, AI employees prepare videos and replies, a person approves each one); give the expected uploads and units a day, with the calculation; describe storage (the 30-day rules, deletion within 7 days of revocation); link the privacy policy and terms; add a screencast and the reviewer account of SH-14.

## 8. Common problems and how they were resolved

Sources: Google's own pages, practitioners' write-ups (§9). Reddit could not be opened from this environment.

| Problem | Usual cause | What fixed it |
|---|---|---|
| `quotaExceeded` on uploads | 100 `videos.insert` calls a day for the whole project | YT-12; YT-E4's per-business cap |
| Uploaded videos stay private | The channel's own default settings. Advice that blames an unverified project describes the 2020 rule | Check the channel's upload defaults; if YouTube says the project needs an audit, YT-12 |
| Custom thumbnail refused | Channel not phone-verified, or verified less than a day ago | §3.4: tell the business |
| `uploadLimitExceeded` | The channel's own daily upload limit | Spread uploads over days; YT-E4 |
| Explorer or Basic access refused after brand verification | Project on the free trial, or its billing suspended or removed | YT-01: a paid billing account |
| `CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION` (v25 and later) or `ACTION_NOT_PERMITTED` (v24 and earlier) | The project still has Test access | GADS-10 |
| `AUTHORIZATION_ERROR` on production calls after an upgrade in September 2026 | A fault Google was rolling out a fix for | Wait for the fix; ask on the Google Ads API forum |
| An old developer token rejected on a new project | Tokens can't be tied to new projects after 9 September 2026 | GADS-E1: rely on the project's access level |
| "Request minimum scopes" | `youtube` or `youtube.force-ssl` asked for while the video shows only uploads | YT-05 |
| Demo video rejected | As for Gmail ([02](02_google.md) §7) | The same fixes |
| Audit refused | Most often what §2 lists: no YouTube statements in the privacy policy or terms, data kept beyond 30 days, actions without the person's consent | SH-07 and SH-08 (§5 of 00), YT-E3, YT-E5; then the appeals form |

## 9. Sources

* YouTube (official): [videos.insert](https://developers.google.com/youtube/v3/docs/videos/insert); [Quota and compliance audits](https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits); [Developer Policies](https://developers.google.com/youtube/terms/developer-policies); [Required Minimum Functionality](https://developers.google.com/youtube/terms/required-minimum-functionality); [Analytics and Reporting API scopes](https://developers.google.com/youtube/reporting/guides/authorization); [Audit and Quota Extension Form](https://support.google.com/youtube/contact/yt_api_form); [Feature access for creators](https://support.google.com/youtube/answer/9890437)
* Google Ads (official): [Access levels](https://developers.google.com/google-ads/api/docs/api-policy/access-levels); [Developer token sunset (9 Sep 2026)](https://developers.google.com/google-ads/api/docs/api-policy/developer-token); [Required Minimum Functionality](https://developers.google.com/google-ads/api/docs/api-policy/rmf); [Video campaigns](https://developers.google.com/google-ads/api/docs/video/overview); [Upload videos](https://developers.google.com/google-ads/api/docs/assets/upload-videos); [Link YouTube](https://developers.google.com/google-ads/api/docs/account-management/linking-youtube); [Sunset dates](https://developers.google.com/google-ads/api/docs/sunset-dates); [Third-party policy](https://support.google.com/adspolicy/answer/6086450); [Enhanced CPC retired](https://support.google.com/google-ads/answer/2390590)
* Google (official): [Sensitive scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification); [Verification FAQ (review times)](https://support.google.com/cloud/answer/13463817)
* Secondary: [YouTube OAuth scopes (Phyllo)](https://www.getphyllo.com/post/youtube-oauth-scopes); [YouTube's synthetic content disclosure (Android Central)](https://www.androidcentral.com/apps-software/youtube-ai-synthetic-content-disclosure); [Thumbnails after phone verification (Ayrshare)](https://www.ayrshare.com/docs/apis/post/social-networks/youtube); [Google Ads API release cadence from v26 (Relevant Audience)](https://www.relevantaudience.com/google-ads-en/google-ads-api-two-releases-a-month-from-v26/)
* This repository: `backend/src/ai/tools/social/youtube.py`, `backend/src/ai/tools/social/google_ads.py`, `backend/src/ai/social_connection_service.py`, `backend/src/connections/client.py`, `backend/src/connections/migrate.py`, `backend/src/gateway/webhook_inbound.py`
