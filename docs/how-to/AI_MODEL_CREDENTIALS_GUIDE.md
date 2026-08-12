# HireBuddha Platform — Credentials & Integration Setup Guide

> **Last Updated:** 2026-03-16  
> **Applies To:** HireBuddha Platform (hb-proto-3)  
> **Policy:** All credentials are stored in the **database** (Integration Registry, Email Connections, Social Connections). Only core application settings (DATABASE_URL, SECRET_KEY, etc.) use environment variables.

---

## Table of Contents

### Part A: AI Model Integrations
1. [Architecture Overview](#1-architecture-overview)
2. [GCP — Vertex AI Setup (Google Gemini & Anthropic Claude)](#2-gcp--vertex-ai-setup-google-gemini--anthropic-claude)
3. [Azure — Azure OpenAI Setup](#3-azure--azure-openai-setup)
4. [Adding AI Credentials to the Integration Registry](#4-adding-credentials-to-the-integration-registry)
5. [Configuring Task Defaults](#5-configuring-task-defaults)
6. [AI Verification & Testing](#6-verification--testing)
7. [AI Troubleshooting](#7-troubleshooting)

### Part B: Third-Party Service Integrations
8. [Twilio — Voice & WhatsApp (International)](#8-twilio--voice--whatsapp-international)
9. [Tata Tele — Voice & WhatsApp (India)](#9-tata-tele--voice--whatsapp-india)
10. [Razorpay — Payment Processing](#10-razorpay--payment-processing)
11. [Firecrawl — Web Scraping](#11-firecrawl--web-scraping)
12. [Google Custom Search — Web Search](#12-google-custom-search--web-search)
13. [SerpAPI — Web Search (Alternative)](#13-serpapi--web-search-alternative)
14. [SMTP / Email — System & Agent Emails](#14-smtp--email--system--agent-emails)
15. [Social Media Platforms — OAuth Connections](#15-social-media-platforms--oauth-connections)
16. [Redis — Session Caching](#16-redis--session-caching)
17. [Playwright — Headless Browser](#17-playwright--headless-browser)
18. [Complete Environment Variables Reference](#18-complete-environment-variables-reference)
19. [Security Checklist](#19-security-checklist)

---

## 1. Architecture Overview

All AI model access in HireBuddha is routed through two cloud providers:

```
┌─────────────────────────────────────────────────────────┐
│                   HireBuddha Backend                     │
│                                                          │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────┐   │
│  │ LLM      │───▶│ Integration  │───▶│ genai_factory│   │
│  │ Router   │    │ Registry (DB)│    │ (Vertex AI)  │   │
│  └──────────┘    └──────────────┘    └──────────────┘   │
│       │                                     │            │
│       │         ┌───────────────┐           │            │
│       └────────▶│ Azure OpenAI  │           │            │
│                 │ Adapter       │           │            │
│                 └───────┬───────┘           │            │
└─────────────────────────┼───────────────────┼────────────┘
                          │                   │
                          ▼                   ▼
                   ┌──────────────┐   ┌──────────────────┐
                   │ Azure OpenAI │   │ Google Cloud      │
                   │ Endpoint     │   │ Vertex AI         │
                   └──────────────┘   │ (Gemini, Claude,  │
                                      │  Embeddings,      │
                                      │  Image/Video Gen) │
                                      └──────────────────┘
```

### Supported Providers

| Provider | Access Method | Models |
|----------|--------------|--------|
| **Google Gemini** | Vertex AI (GCP) | gemini-2.0-flash, gemini-2.5-flash, gemini-2.5-pro |
| **Anthropic Claude** | Vertex AI (GCP) | claude-3-5-sonnet, claude-3-opus, claude-3-haiku |
| **Azure OpenAI** | Azure Endpoint | gpt-4o, gpt-4o-mini, gpt-4o-realtime-preview |
| **Google Embeddings** | Vertex AI (GCP) | text-embedding-004, gemini-embedding-004 |
| **Google Image Gen** | Vertex AI (GCP) | gemini-3-pro-image-preview |
| **Google Video Gen** | Vertex AI (GCP) | veo-3.1-generate-preview |

---

## 2. GCP — Vertex AI Setup (Google Gemini & Anthropic Claude)

Vertex AI on GCP is used for **all Google Gemini models** (text, embeddings, image, video, live audio) and **Anthropic Claude models**.

### Step 2.1: Create a GCP Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click **"Select a Project"** → **"New Project"**
3. Enter a project name (e.g., `hirebuddha-prod`)
4. Note down the **Project ID** (e.g., `hirebuddha-prod-abc123`) — you'll need this later
5. Make sure billing is enabled for the project

### Step 2.2: Enable Required APIs

Run these commands in Google Cloud Shell or with `gcloud` CLI installed:

```bash
# Set your project
gcloud config set project YOUR_PROJECT_ID

# Enable Vertex AI API (required for all Gemini models)
gcloud services enable aiplatform.googleapis.com

# Enable Generative AI API (for Gemini models specifically)
gcloud services enable generativelanguage.googleapis.com

# Enable Cloud Resource Manager (for project metadata)
gcloud services enable cloudresourcemanager.googleapis.com
```

Or enable them via the Console:
1. Go to **APIs & Services** → **Library**
2. Search for and enable:
   - **Vertex AI API**
   - **Generative Language API**

### Step 2.3: Enable Anthropic Claude on Vertex AI (Optional)

If you want to use Anthropic Claude models via Vertex AI:

1. Go to [Vertex AI Model Garden](https://console.cloud.google.com/vertex-ai/model-garden)
2. Search for **"Claude"**
3. Click on **Claude 3.5 Sonnet** (or your desired model)
4. Click **"Enable"** and accept the terms
5. Note the **region** where Claude is available (usually `us-east5` or `europe-west1`)

### Step 2.4: Create a Service Account

1. Go to **IAM & Admin** → **Service Accounts**
2. Click **"+ Create Service Account"**
3. Fill in:
   - **Name:** `hirebuddha-vertex-ai`
   - **Description:** `Service account for HireBuddha Vertex AI access`
4. Click **Create and Continue**
5. Add these roles:
   - `Vertex AI User` (roles/aiplatform.user)
   - `Vertex AI Service Agent` (roles/aiplatform.serviceAgent) — if using Model Garden models
6. Click **Done**

### Step 2.5: Generate a Service Account Key

> **⚠️ Important:** Service account keys are sensitive credentials. For production, consider using Workload Identity Federation instead.

**Option A: JSON Key File (simpler, for development/testing)**

1. Click on the service account you just created
2. Go to **Keys** tab
3. Click **"Add Key"** → **"Create new key"**
4. Select **JSON** format
5. Click **Create** — a `.json` file will be downloaded
6. Save this file securely on your server (e.g., `/etc/hirebuddha/gcp-service-account.json`)
7. Set the environment variable on your server:

```bash
export GOOGLE_APPLICATION_CREDENTIALS="/etc/hirebuddha/gcp-service-account.json"
```

Add this to your service startup script or systemd unit file.

**Option B: Workload Identity Federation (recommended for production)**

If your backend runs on GCP (GKE, Cloud Run, Compute Engine), attach the service account directly:

```bash
# For Compute Engine
gcloud compute instances set-service-account YOUR_INSTANCE \
    --service-account=hirebuddha-vertex-ai@YOUR_PROJECT_ID.iam.gserviceaccount.com \
    --scopes=https://www.googleapis.com/auth/cloud-platform

# For GKE
kubectl annotate serviceaccount default \
    iam.gke.io/gcp-service-account=hirebuddha-vertex-ai@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

No key file needed — the SDK uses Application Default Credentials (ADC) automatically.

### Step 2.6: Verify Vertex AI Access

Test from your server:

```bash
# Install the SDK if not already installed
pip install google-genai

# Quick test
python3 -c "
from google import genai
client = genai.Client(vertexai=True, project='YOUR_PROJECT_ID', location='us-central1')
response = client.models.generate_content(
    model='gemini-2.0-flash',
    contents='Hello, world!'
)
print(response.text)
"
```

If this works, your Vertex AI setup is complete!

### Step 2.7: Note Down Your Configuration

You'll need these values for the Integration Registry:

| Field | Value | Example |
|-------|-------|---------|
| `project_id` | Your GCP project ID | `hirebuddha-prod-abc123` |
| `region` (Gemini) | Vertex AI region for Gemini | `us-central1` |
| `region` (Claude) | Vertex AI region for Claude | `us-east5` |

---

## 3. Azure — Azure OpenAI Setup

Azure OpenAI is used for **GPT-4o**, **GPT-4o-mini**, and **GPT-4o Realtime** models.

### Step 3.1: Create an Azure OpenAI Resource

1. Go to [Azure Portal](https://portal.azure.com/)
2. Click **"Create a Resource"** → Search for **"Azure OpenAI"**
3. Click **Create**
4. Fill in:
   - **Subscription:** Your Azure subscription
   - **Resource Group:** Create new or select existing (e.g., `hirebuddha-rg`)
   - **Region:** Select a region that supports the models you need
     - `East US`, `East US 2`, `West US` — support GPT-4o
     - `Sweden Central` — supports GPT-4o Realtime
   - **Name:** `hirebuddha-openai` (this becomes part of your endpoint URL)
   - **Pricing Tier:** Standard S0
5. Click **Review + Create** → **Create**
6. Wait for deployment to complete

### Step 3.2: Deploy Models

1. Go to your Azure OpenAI resource
2. Click **"Go to Azure AI Foundry portal"** (or Azure OpenAI Studio)
3. Go to **Deployments** → **"+ Create new deployment"**
4. Deploy the models you need:

| Model | Deployment Name (you choose) | Recommended |
|-------|------------------------------|-------------|
| gpt-4o | `gpt-4o` | ✅ Primary text generation |
| gpt-4o-mini | `gpt-4o-mini` | ✅ Cost-efficient tasks |
| gpt-4o-realtime-preview | `gpt-4o-realtime` | For speech_to_speech |

5. For each deployment, note down:
   - **Deployment Name** — you'll need this for `deployment_name` in service_metadata
   - **Model Version** — e.g., `2024-11-20`

### Step 3.3: Get Your API Key and Endpoint

1. Go to your Azure OpenAI resource in the Azure Portal
2. Click **"Keys and Endpoint"** in the left menu
3. Note down:
   - **KEY 1** (or KEY 2 — either works) → This is your `api_key`
   - **Endpoint** → e.g., `https://hirebuddha-openai.openai.azure.com/`
4. Note down the **API Version** — use the latest: `2025-04-01-preview`

### Step 3.4: Verify Azure OpenAI Access

```bash
# Install the SDK
pip install openai

# Quick test
python3 -c "
from openai import AzureOpenAI
client = AzureOpenAI(
    api_key='YOUR_API_KEY',
    azure_endpoint='https://hirebuddha-openai.openai.azure.com/',
    api_version='2025-04-01-preview'
)
response = client.chat.completions.create(
    model='gpt-4o',  # This is the DEPLOYMENT NAME
    messages=[{'role': 'user', 'content': 'Hello!'}]
)
print(response.choices[0].message.content)
"
```

### Step 3.5: Note Down Your Configuration

| Field | Value | Example |
|-------|-------|---------|
| `api_key` | Azure OpenAI API key (KEY 1 or KEY 2) | `abc123...` |
| `azure_endpoint` | Resource endpoint URL | `https://hirebuddha-openai.openai.azure.com/` |
| `api_version` | API version string | `2025-04-01-preview` |
| `deployment_name` | Model deployment name | `gpt-4o` |

---

## 4. Adding Credentials to the Integration Registry

Now that you have your GCP and Azure credentials, add them to HireBuddha's Integration Registry.

### Method A: Via the API (Recommended)

Use the REST API endpoint `POST /api/config/integrations`.

You need to be logged in as an **app_admin** or **tenant_admin**.

#### 4.1: Register Google Gemini (Vertex AI)

```bash
# Get your auth token first (login via the UI or API)
AUTH_TOKEN="your-jwt-token"
COMPANY_ID="your-company-uuid"

# --- Gemini 2.0 Flash (Text Generation) ---
curl -X POST "https://your-domain.com/api/config/integrations" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "company_id": "'$COMPANY_ID'",
    "provider_name": "google",
    "model_name": "gemini-2.0-flash",
    "service_sku": "gemini-2.0-flash-in",
    "service_category": "LLM",
    "component_type": "input_token",
    "api_key": "vertex-ai-service-account",
    "internal_cost": 0.000075,
    "cost_unit": "per_1k_tokens",
    "service_metadata": {
      "project_id": "YOUR_GCP_PROJECT_ID",
      "region": "us-central1"
    }
  }'

# --- Gemini 2.5 Flash (Text Generation) ---
curl -X POST "https://your-domain.com/api/config/integrations" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "company_id": "'$COMPANY_ID'",
    "provider_name": "google",
    "model_name": "gemini-2.5-flash-preview-05-20",
    "service_sku": "gemini-2.5-flash-in",
    "service_category": "LLM",
    "component_type": "input_token",
    "api_key": "vertex-ai-service-account",
    "internal_cost": 0.00015,
    "cost_unit": "per_1k_tokens",
    "service_metadata": {
      "project_id": "YOUR_GCP_PROJECT_ID",
      "region": "us-central1"
    }
  }'

# --- Gemini Embeddings ---
curl -X POST "https://your-domain.com/api/config/integrations" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "company_id": "'$COMPANY_ID'",
    "provider_name": "google",
    "model_name": "gemini-embedding-004",
    "service_sku": "gemini-embedding-004",
    "service_category": "LLM",
    "component_type": "input_token",
    "api_key": "vertex-ai-service-account",
    "internal_cost": 0.000010,
    "cost_unit": "per_1k_tokens",
    "service_metadata": {
      "project_id": "YOUR_GCP_PROJECT_ID",
      "region": "us-central1"
    }
  }'

# --- Gemini Live Audio (Speech-to-Speech) ---
curl -X POST "https://your-domain.com/api/config/integrations" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "company_id": "'$COMPANY_ID'",
    "provider_name": "google",
    "model_name": "gemini-2.5-flash-preview-native-audio-01",
    "service_sku": "gemini-2.5-flash-live",
    "service_category": "LLM_LIVE",
    "component_type": "minute",
    "api_key": "vertex-ai-service-account",
    "internal_cost": 0.040,
    "cost_unit": "per_minute",
    "service_metadata": {
      "project_id": "YOUR_GCP_PROJECT_ID",
      "region": "us-central1"
    }
  }'

# --- Image Generation ---
curl -X POST "https://your-domain.com/api/config/integrations" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "company_id": "'$COMPANY_ID'",
    "provider_name": "google",
    "model_name": "gemini-3-pro-image-preview",
    "service_sku": "gemini-image-gen",
    "service_category": "IMAGE_GENERATION",
    "component_type": "image",
    "api_key": "vertex-ai-service-account",
    "internal_cost": 0.040,
    "cost_unit": "per_image",
    "service_metadata": {
      "project_id": "YOUR_GCP_PROJECT_ID",
      "region": "us-central1"
    }
  }'

# --- Video Generation ---
curl -X POST "https://your-domain.com/api/config/integrations" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "company_id": "'$COMPANY_ID'",
    "provider_name": "google",
    "model_name": "veo-3.1-generate-preview",
    "service_sku": "veo-3.1-video-gen",
    "service_category": "VIDEO_GENERATION",
    "component_type": "video_second",
    "api_key": "vertex-ai-service-account",
    "internal_cost": 0.350,
    "cost_unit": "per_video",
    "service_metadata": {
      "project_id": "YOUR_GCP_PROJECT_ID",
      "region": "us-central1"
    }
  }'
```

> **Note on `api_key` field:** For Vertex AI, the actual authentication is handled by the GCP Service Account (via `GOOGLE_APPLICATION_CREDENTIALS` environment variable or Workload Identity). The `api_key` field in the Integration Registry is stored but not used for authentication — Vertex AI uses Application Default Credentials (ADC). You can set it to any placeholder value like `"vertex-ai-service-account"`.

#### 4.2: Register Anthropic Claude (via Vertex AI)

```bash
# --- Claude 3.5 Sonnet ---
curl -X POST "https://your-domain.com/api/config/integrations" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "company_id": "'$COMPANY_ID'",
    "provider_name": "anthropic",
    "model_name": "claude-3-5-sonnet-v2@20241022",
    "service_sku": "claude-3-5-sonnet-in",
    "service_category": "LLM",
    "component_type": "input_token",
    "api_key": "vertex-ai-service-account",
    "internal_cost": 0.003,
    "cost_unit": "per_1k_tokens",
    "service_metadata": {
      "project_id": "YOUR_GCP_PROJECT_ID",
      "region": "us-east5"
    }
  }'
```

> **Important:** Claude on Vertex AI is only available in specific regions. Check the [Claude on Vertex AI docs](https://docs.anthropic.com/en/docs/about-claude/models#model-availability) for current availability. Common regions:
> - `us-east5` (Ohio)
> - `europe-west1` (Belgium)

#### 4.3: Register Azure OpenAI

```bash
# --- GPT-4o ---
curl -X POST "https://your-domain.com/api/config/integrations" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "company_id": "'$COMPANY_ID'",
    "provider_name": "azure_openai",
    "model_name": "gpt-4o",
    "service_sku": "gpt-4o-in",
    "service_category": "LLM",
    "component_type": "input_token",
    "api_key": "YOUR_AZURE_OPENAI_API_KEY",
    "internal_cost": 0.0025,
    "cost_unit": "per_1k_tokens",
    "service_metadata": {
      "azure_endpoint": "https://YOUR-RESOURCE-NAME.openai.azure.com/",
      "api_version": "2025-04-01-preview",
      "deployment_name": "gpt-4o"
    }
  }'

# --- GPT-4o Mini ---
curl -X POST "https://your-domain.com/api/config/integrations" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "company_id": "'$COMPANY_ID'",
    "provider_name": "azure_openai",
    "model_name": "gpt-4o-mini",
    "service_sku": "gpt-4o-mini-in",
    "service_category": "LLM",
    "component_type": "input_token",
    "api_key": "YOUR_AZURE_OPENAI_API_KEY",
    "internal_cost": 0.000150,
    "cost_unit": "per_1k_tokens",
    "service_metadata": {
      "azure_endpoint": "https://YOUR-RESOURCE-NAME.openai.azure.com/",
      "api_version": "2025-04-01-preview",
      "deployment_name": "gpt-4o-mini"
    }
  }'

# --- GPT-4o Realtime (for speech-to-speech) ---
curl -X POST "https://your-domain.com/api/config/integrations" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "company_id": "'$COMPANY_ID'",
    "provider_name": "azure_openai",
    "model_name": "gpt-4o-realtime-preview",
    "service_sku": "gpt-4o-realtime-in",
    "service_category": "LLM_LIVE",
    "component_type": "minute",
    "api_key": "YOUR_AZURE_OPENAI_API_KEY",
    "internal_cost": 0.060,
    "cost_unit": "per_minute",
    "service_metadata": {
      "azure_endpoint": "https://YOUR-RESOURCE-NAME.openai.azure.com/",
      "api_version": "2025-04-01-preview",
      "deployment_name": "gpt-4o-realtime"
    }
  }'
```

### Method B: Direct Database Insert

If you prefer to insert directly into the database:

```sql
-- Replace placeholders with actual values

-- Google Gemini 2.0 Flash via Vertex AI
INSERT INTO integration_registry (
    id, company_id, provider_name, model_name, service_sku,
    service_category, component_type, encrypted_api_key,
    internal_cost, cost_unit, service_metadata, status
) VALUES (
    gen_random_uuid(),
    'YOUR_COMPANY_UUID',
    'google',
    'gemini-2.0-flash',
    'gemini-2.0-flash-in',
    'LLM',
    'input_token',
    -- Use the encrypt_api_key() function from your Python code to encrypt:
    -- from src.common.security import encrypt_api_key
    -- encrypt_api_key('vertex-ai-service-account')
    'ENCRYPTED_PLACEHOLDER',
    0.000075,
    'per_1k_tokens',
    '{"project_id": "YOUR_GCP_PROJECT_ID", "region": "us-central1"}'::jsonb,
    'active'
);

-- Azure OpenAI GPT-4o
INSERT INTO integration_registry (
    id, company_id, provider_name, model_name, service_sku,
    service_category, component_type, encrypted_api_key,
    internal_cost, cost_unit, service_metadata, status
) VALUES (
    gen_random_uuid(),
    'YOUR_COMPANY_UUID',
    'azure_openai',
    'gpt-4o',
    'gpt-4o-in',
    'LLM',
    'input_token',
    'ENCRYPTED_API_KEY_HERE',
    0.0025,
    'per_1k_tokens',
    '{"azure_endpoint": "https://YOUR-RESOURCE.openai.azure.com/", "api_version": "2025-04-01-preview", "deployment_name": "gpt-4o"}'::jsonb,
    'active'
);
```

> **⚠️ Warning:** API keys must be encrypted before storing in the database. Use the Python encryption utility:
> ```python
> from src.common.security import encrypt_api_key
> encrypted = encrypt_api_key("your-actual-api-key")
> print(encrypted)  # Use this value in SQL
> ```

---

## 5. Configuring Task Defaults

After registering integrations, you need to tell HireBuddha which model to use for each task type. This is done via **Task Defaults**.

### Available Task Types

| Task Type | Description | Recommended Model |
|-----------|-------------|-------------------|
| `text_generation` | Chat, Q&A, summarization | gemini-2.0-flash or gpt-4o |
| `thinking` | Complex reasoning, planning | gemini-2.5-flash or claude-3-5-sonnet |
| `text_to_image` | Image generation from text | gemini-3-pro-image-preview |
| `text_to_video` | Video generation from text | veo-3.1-generate-preview |
| `speech_to_speech` | Real-time voice conversation | gemini-2.5-flash-live or gpt-4o-realtime |
| `text_to_speech` | Text to audio speech | (configure as needed) |
| `image_to_image` | Image editing/transformation | gemini-3-pro-image-preview |
| `image_to_video` | Animate images to video | veo-3.1-generate-preview |

### Setting Task Defaults via API

```bash
# First, get the integration IDs
curl -s "https://your-domain.com/api/config/integrations" \
  -H "Authorization: Bearer $AUTH_TOKEN" | python3 -m json.tool

# Note the 'id' field of each integration you want to assign

# Set text_generation default to Gemini 2.0 Flash
curl -X POST "https://your-domain.com/api/config/task-defaults" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "task_type": "text_generation",
    "integration_id": "GEMINI_FLASH_INTEGRATION_UUID",
    "routing_mode": "single"
  }'

# Set thinking default to Claude 3.5 Sonnet
curl -X POST "https://your-domain.com/api/config/task-defaults" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "task_type": "thinking",
    "integration_id": "CLAUDE_SONNET_INTEGRATION_UUID",
    "routing_mode": "single"
  }'

# Set speech_to_speech default to Gemini Live
curl -X POST "https://your-domain.com/api/config/task-defaults" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "task_type": "speech_to_speech",
    "integration_id": "GEMINI_LIVE_INTEGRATION_UUID",
    "routing_mode": "single"
  }'

# Set text_to_image default
curl -X POST "https://your-domain.com/api/config/task-defaults" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "task_type": "text_to_image",
    "integration_id": "GEMINI_IMAGE_GEN_INTEGRATION_UUID",
    "routing_mode": "single"
  }'

# Set text_to_video default
curl -X POST "https://your-domain.com/api/config/task-defaults" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "task_type": "text_to_video",
    "integration_id": "VEO_VIDEO_GEN_INTEGRATION_UUID",
    "routing_mode": "single"
  }'
```

---

## 6. Verification & Testing

### 6.1: Check Registered Integrations

```bash
curl -s "https://your-domain.com/api/config/integrations" \
  -H "Authorization: Bearer $AUTH_TOKEN" | python3 -m json.tool
```

Verify each integration has:
- ✅ `status: "active"`
- ✅ `service_metadata` contains `project_id` (for Google/Anthropic) or `azure_endpoint` (for Azure)
- ✅ `model_name` is correct

### 6.2: Check Task Defaults

```bash
curl -s "https://your-domain.com/api/config/task-defaults" \
  -H "Authorization: Bearer $AUTH_TOKEN" | python3 -m json.tool
```

Verify each task type you need is mapped to the correct integration.

### 6.3: Test Vertex AI Connectivity

```bash
# From your server, test that ADC (Application Default Credentials) works
python3 -c "
from google import genai
client = genai.Client(vertexai=True, project='YOUR_PROJECT_ID', location='us-central1')
r = client.models.generate_content(model='gemini-2.0-flash', contents='Say hello in one word')
print('✅ Vertex AI works:', r.text)
"
```

### 6.4: Test Azure OpenAI Connectivity

```bash
python3 -c "
from openai import AzureOpenAI
client = AzureOpenAI(
    api_key='YOUR_KEY',
    azure_endpoint='https://YOUR-RESOURCE.openai.azure.com/',
    api_version='2025-04-01-preview'
)
r = client.chat.completions.create(
    model='gpt-4o',
    messages=[{'role': 'user', 'content': 'Say hello in one word'}]
)
print('✅ Azure OpenAI works:', r.choices[0].message.content)
"
```

### 6.5: Test End-to-End via LLM Router

```bash
# Send a chat message to an entity to test the full pipeline
curl -X POST "https://your-domain.com/api/ai/entities/YOUR_ENTITY_ID/chat" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello, can you hear me?"}'
```

---

## 7. Troubleshooting

### Common Error: "service_metadata.project_id is required for Vertex AI"

**Cause:** Your Integration Registry entry for Google/Gemini is missing `project_id` in `service_metadata`.

**Fix:**
```bash
# Update the integration to include project_id
curl -X PATCH "https://your-domain.com/api/config/integrations/INTEGRATION_UUID" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "service_metadata": {
      "project_id": "your-gcp-project-id",
      "region": "us-central1"
    }
  }'
```

### Common Error: "No Google/Gemini integration configured"

**Cause:** No integration with `provider_name = "google"` or `"gemini"` exists for your company.

**Fix:** Create the integration using the curl commands in Section 4.1.

### Common Error: "Could not automatically determine credentials"

**Cause:** The `GOOGLE_APPLICATION_CREDENTIALS` environment variable is not set, or the service account key file doesn't exist.

**Fix:**
```bash
# Verify the env var is set
echo $GOOGLE_APPLICATION_CREDENTIALS

# Verify the file exists
ls -la $GOOGLE_APPLICATION_CREDENTIALS

# If missing, set it
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/your/service-account-key.json"
```

### Common Error: "azure_endpoint required in service_metadata"

**Cause:** Your Azure OpenAI integration is missing `azure_endpoint` in `service_metadata`.

**Fix:**
```bash
curl -X PATCH "https://your-domain.com/api/config/integrations/INTEGRATION_UUID" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "service_metadata": {
      "azure_endpoint": "https://your-resource.openai.azure.com/",
      "api_version": "2025-04-01-preview",
      "deployment_name": "gpt-4o"
    }
  }'
```

### Common Error: "403 Permission denied on Vertex AI"

**Cause:** The service account doesn't have the required roles.

**Fix:**
```bash
# Grant Vertex AI User role
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:hirebuddha-vertex-ai@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"
```

### Common Error: "Model not found in region"

**Cause:** The model isn't available in the specified region.

**Fix:** Check Google's [model availability page](https://cloud.google.com/vertex-ai/generative-ai/docs/learn/models) and update the `region` in your `service_metadata`.

---

## Quick Reference: Required `service_metadata` Fields

### Google Gemini (Vertex AI)
```json
{
  "project_id": "your-gcp-project-id",    // REQUIRED
  "region": "us-central1"                   // optional, defaults to us-central1
}
```

### Anthropic Claude (Vertex AI)
```json
{
  "project_id": "your-gcp-project-id",    // REQUIRED
  "region": "us-east5"                      // REQUIRED (Claude has limited regions)
}
```

### Azure OpenAI
```json
{
  "azure_endpoint": "https://your-resource.openai.azure.com/",  // REQUIRED
  "api_version": "2025-04-01-preview",                           // REQUIRED
  "deployment_name": "gpt-4o"                                    // optional (defaults to model_name)
}
```

---

## 19. Security Checklist

### AI Models
- [ ] GCP Service Account key file stored securely with `chmod 600`
- [ ] `GOOGLE_APPLICATION_CREDENTIALS` set in service startup
- [ ] Azure OpenAI API keys encrypted in database (auto-handled by API)
- [ ] No API keys hardcoded in source code
- [ ] No `os.getenv()` fallbacks for any third-party service credentials

### Communication Services
- [ ] Twilio credentials stored in Integration Registry (`provider_name = "twilio"`)
- [ ] Tata Tele credentials stored in Integration Registry (`provider_name = "tata_tele"`)
- [ ] Webhook URLs use HTTPS only

### Payment Processing
- [ ] Razorpay `key_id` and `key_secret` stored in `service_metadata` (not in code)
- [ ] Razorpay integration registered with `service_sku = "razorpay_keys"`

### Email
- [ ] System SMTP credentials stored in Integration Registry (`service_sku = "smtp-system"`)
- [ ] Agent email app passwords stored encrypted in `email_connections` table

### Social Media
- [ ] OAuth tokens stored encrypted in `social_connections` table
- [ ] Token refresh mechanism working for platforms with expiring tokens

### General
- [ ] `ENCRYPTION_MASTER_KEY` is a strong 32-byte secret (not the default dev key)
- [ ] `SECRET_KEY` for JWT tokens is a strong random secret
- [ ] API keys are rotated periodically
- [ ] Service accounts have minimum required roles (least privilege)
- [ ] `.env` file contains ONLY core settings (no third-party keys)

---

# Part B: Third-Party Service Integrations

---

## 8. Twilio — Voice & WhatsApp (International)

Twilio powers **outbound voice calls**, **WebSocket audio streaming**, and **WhatsApp messaging** for international numbers.

### 8.1: Create a Twilio Account

1. Go to [Twilio Console](https://www.twilio.com/console)
2. Sign up or log in
3. From the Dashboard, note down:
   - **Account SID** (e.g., `ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`)
   - **Auth Token** (click "Show" to reveal)

### 8.2: Get a Phone Number

1. Go to **Phone Numbers** → **Manage** → **Buy a Number**
2. Select a number with **Voice** and **SMS** capabilities
3. For WhatsApp: Go to **Messaging** → **Try it Out** → **Send a WhatsApp message** to set up a WhatsApp sandbox (or apply for a WhatsApp Business API number for production)

### 8.3: Configure Webhooks

In the Twilio Console, configure your webhook URLs:

| Webhook | URL | Method |
|---------|-----|--------|
| Voice incoming | `https://your-domain.com/webhooks/voice/twilio/incoming` | POST |
| Voice status callback | `https://your-domain.com/webhooks/voice/twilio/status` | POST |
| WhatsApp incoming | `https://your-domain.com/webhooks/whatsapp/twilio/incoming` | POST |
| Media Stream (WebSocket) | `wss://your-domain.com/stream/twilio/{session_id}` | WebSocket |

### 8.4: Register in Integration Registry

```bash
curl -X POST "https://your-domain.com/api/config/integrations" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "company_id": "'$COMPANY_ID'",
    "provider_name": "twilio",
    "service_sku": "twilio-voice-whatsapp",
    "service_category": "COMMUNICATION",
    "component_type": "call_minute",
    "api_key": "YOUR_TWILIO_AUTH_TOKEN",
    "internal_cost": 0.013,
    "cost_unit": "per_minute",
    "service_metadata": {
      "account_sid": "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "from_number": "+14155238886"
    }
  }'
```

> **Used by:** `voice/whatsapp_messaging.py`, `ai/campaign_executor.py`  
> **Credential resolution:** `account_sid` from `service_metadata`, `auth_token` from `api_key` (encrypted).

---

## 9. Tata Tele — Voice & WhatsApp (India)

Tata Tele Business Services provides **WhatsApp Business API** and **voice** for Indian phone numbers (+91).

### 9.1: Create a Tata Tele Account

1. Go to [Tata Tele Business Services](https://www.tatatelebusiness.com/)
2. Sign up for the **SmartFlo** platform
3. Apply for WhatsApp Business API access
4. Get your credentials from the SmartFlo dashboard:
   - **API Key**
   - **API Secret**
   - **Business ID**

### 9.2: Configure WhatsApp Templates

1. In the SmartFlo portal, go to **WhatsApp** → **Templates**
2. Create and get approval for your message templates
3. Note down template IDs for programmatic use

### 9.3: Register in Integration Registry

```bash
curl -X POST "https://your-domain.com/api/config/integrations" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "company_id": "'$COMPANY_ID'",
    "provider_name": "tata_tele",
    "service_sku": "tata-tele-voice-whatsapp",
    "service_category": "COMMUNICATION",
    "component_type": "call_minute",
    "api_key": "YOUR_TATA_TELE_API_KEY",
    "internal_cost": 0.01,
    "cost_unit": "per_minute",
    "service_metadata": {
      "api_key": "YOUR_TATA_TELE_API_KEY",
      "api_secret": "YOUR_TATA_TELE_API_SECRET",
      "business_id": "YOUR_BUSINESS_ID",
      "from_number": "+919876543210",
      "api_url": "https://api-smartflo.tatateleservices.com"
    }
  }'
```

> **Used by:** `voice/whatsapp_messaging.py`, `voice/webhook_router.py`  
> **Credential resolution:** All fields from `service_metadata`.  
> **Routing:** The platform auto-detects provider by phone number country code — Indian numbers (+91) route to Tata Tele, all others to Twilio.

---

## 10. Razorpay — Payment Processing

Razorpay handles **subscription billing**, **auto-debit mandates**, and **credit top-ups**.

### 10.1: Create a Razorpay Account

1. Go to [Razorpay Dashboard](https://dashboard.razorpay.com/)
2. Sign up and complete KYC verification
3. Go to **Settings** → **API Keys**
4. Click **Generate Key** to get:
   - **Key ID** (e.g., `rzp_live_xxxxxxxxxxxx`)
   - **Key Secret** (shown once — save it!)

### 10.2: Create Subscription Plans

1. In Razorpay Dashboard, go to **Subscriptions** → **Plans**
2. Create plans matching your tiers (e.g., Starter, Growth, Enterprise)
3. Note down the **Plan IDs** (e.g., `plan_xxxxxxxxxxxxxxx`)

### 10.3: Register in Integration Registry

Razorpay credentials go into the Integration Registry with `service_sku = "razorpay_keys"`:

```bash
curl -X POST "https://your-domain.com/api/config/integrations" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "company_id": "'$COMPANY_ID'",
    "provider_name": "razorpay",
    "model_name": null,
    "service_sku": "razorpay_keys",
    "service_category": "PAYMENT",
    "component_type": "transaction",
    "api_key": "rzp_live_xxxxxxxxxxxx",
    "internal_cost": 0.02,
    "cost_unit": "per_transaction_pct",
    "service_metadata": {
      "key_id": "rzp_live_xxxxxxxxxxxx",
      "key_secret": "YOUR_RAZORPAY_KEY_SECRET"
    }
  }'
```

> **⚠️ Important:** Both `key_id` and `key_secret` must be in `service_metadata`. The cron service reads them from there. See `billing/cron_service.py`.

> **Python package required:** `pip install razorpay`

---

## 11. Firecrawl — Web Scraping

Firecrawl provides intelligent web scraping, converting web pages to clean Markdown.

### 11.1: Get API Key

1. Go to [Firecrawl](https://www.firecrawl.dev/)
2. Sign up and get your API key from the dashboard

### 11.2: Register in Integration Registry

```bash
curl -X POST "https://your-domain.com/api/config/integrations" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "company_id": "'$COMPANY_ID'",
    "provider_name": "firecrawl",
    "model_name": null,
    "service_sku": "firecrawl-api",
    "service_category": "SCRAPING",
    "component_type": "page_scrape",
    "api_key": "fc-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "internal_cost": 0.001,
    "cost_unit": "per_page"
  }'
```

> **Used by:** `ai/tools/scraper.py` — The `ScraperTool` looks up the key via `config_service.get_api_key_by_provider(company_id, "firecrawl")`.

---

## 12. Google Custom Search — Web Search

Google Custom Search Engine (CSE) provides high-quality web search results.

### 12.1: Create a Custom Search Engine

1. Go to [Google Custom Search](https://cse.google.com/cse/)
2. Click **New Search Engine**
3. Under "Sites to Search", enter `*.com` (to search the entire web)
4. Click **Create**
5. Go to the CSE's **Overview** page and note the **Search Engine ID** (cx)

### 12.2: Get an API Key

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Enable the **Custom Search API**:
   ```bash
   gcloud services enable customsearch.googleapis.com
   ```
3. Go to **APIs & Services** → **Credentials** → **Create Credentials** → **API Key**
4. Restrict the key to **Custom Search API** only (recommended)

### 12.3: Register in Integration Registry

```bash
curl -X POST "https://your-domain.com/api/config/integrations" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "company_id": "'$COMPANY_ID'",
    "provider_name": "google",
    "service_sku": "google-cse-key",
    "service_category": "SEARCH",
    "component_type": "search_query",
    "api_key": "AIzaSyxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "internal_cost": 0.005,
    "cost_unit": "per_query",
    "service_metadata": {
      "cse_id": "a1b2c3d4e5f6g7h8i"
    }
  }'
```

> **Used by:** `ai/tools/search.py` — Priority #1 backend. Falls back to SerpAPI → DuckDuckGo if not configured.

---

## 13. SerpAPI — Web Search (Alternative)

SerpAPI provides Google search results via a managed API. Used as a fallback if Google CSE is not configured.

### 13.1: Get API Key

1. Go to [SerpAPI](https://serpapi.com/)
2. Sign up and get your API key from the dashboard

### 13.2: Register in Integration Registry

```bash
curl -X POST "https://your-domain.com/api/config/integrations" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "company_id": "'$COMPANY_ID'",
    "provider_name": "serpapi",
    "service_sku": "serp-api-key",
    "service_category": "SEARCH",
    "component_type": "search_query",
    "api_key": "YOUR_SERPAPI_KEY",
    "internal_cost": 0.005,
    "cost_unit": "per_query"
  }'
```

> **Used by:** `ai/tools/search.py` — Priority #2 backend (after Google CSE).

> **Free fallback:** If neither Google CSE nor SerpAPI are configured, the search tool falls back to DuckDuckGo (no API key needed).

---

## 14. SMTP / Email — System & Agent Emails

Two separate email systems exist:

### 14A: System Emails (Verification, Dunning)

System emails (account verification, payment failure notices) use SMTP. Credentials are stored in the Integration Registry with `service_sku = "smtp-system"`.

```bash
curl -X POST "https://your-domain.com/api/config/integrations" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "company_id": "'$COMPANY_ID'",
    "provider_name": "smtp",
    "service_sku": "smtp-system",
    "service_category": "EMAIL",
    "component_type": "email_send",
    "api_key": "YOUR_SMTP_PASSWORD",
    "internal_cost": 0.0,
    "cost_unit": "per_email",
    "service_metadata": {
      "smtp_host": "smtp.gmail.com",
      "smtp_port": 587,
      "smtp_user": "notifications@yourdomain.com",
      "smtp_from": "notifications@yourdomain.com"
    }
  }'
```

> **Used by:** `common/email.py` — `EmailService` loads credentials lazily on first email send.  
> **For Gmail:** Use an [App Password](https://myaccount.google.com/apppasswords), not your regular password.

### 14B: AI Agent Emails (IMAP/SMTP per Company)

AI agents can read, classify, draft, and send emails on behalf of companies. Per-company email credentials are stored in the `email_connections` database table.

**To add via API** (the frontend provides a UI for this):

The `email_connections` table stores:
| Field | Example |
|-------|---------|
| `email_address` | `support@customer.com` |
| `encrypted_app_password` | (encrypted via `encrypt_api_key`) |
| `imap_host` | `imap.gmail.com` |
| `imap_port` | `993` |
| `smtp_host` | `smtp.gmail.com` |
| `smtp_port` | `587` |

**For Gmail:**
1. Enable 2-Factor Authentication on the Google account
2. Go to [Google App Passwords](https://myaccount.google.com/apppasswords)
3. Generate an **App Password** for "Mail"
4. Use this App Password as the `password` field

> **Used by:** `ai/tools/email_tool.py` — EmailIngestTool, EmailClassifyTool, EmailDraftTool, EmailSendTool

---

## 15. Social Media Platforms — OAuth Connections

HireBuddha supports **17 social media platforms** via OAuth-based connections. Credentials are stored in the `social_connections` database table (encrypted).

### Supported Platforms

| Platform | Tool File | OAuth Required | Capabilities |
|----------|-----------|----------------|--------------|
| LinkedIn | `social/linkedin.py` | ✅ | Post, read feed, profile |
| LinkedIn Ads | `social/linkedin_ads.py` | ✅ | Campaign management |
| LinkedIn Sales Nav | `social/linkedin_sales_nav.py` | ✅ | Lead search, messaging |
| Facebook | `social/facebook.py` | ✅ | Page posts, insights |
| Instagram | `social/instagram.py` | ✅ | Posts, stories, reels |
| Twitter/X | `social/twitter.py` | ✅ | Tweets, threads |
| X Ads | `social/x_ads.py` | ✅ | Ad campaigns |
| YouTube | `social/youtube.py` | ✅ | Video upload, analytics |
| YouTube Ads | `social/youtube_ads.py` | ✅ | Google Ads for YouTube |
| Meta Ads | `social/meta_ads.py` | ✅ | Facebook/Instagram ads |
| Google Ads | `social/google_ads.py` | ✅ | Search & display ads |
| Pinterest | `social/pinterest.py` | ✅ | Pins, boards |
| Reddit | `social/reddit.py` | ✅ | Posts, comments |
| TikTok | `social/tiktok.py` | ✅ | Video posts |
| Snapchat Ads | `social/snapchat_ads.py` | ✅ | Snap ad campaigns |
| Quora | `social/quora.py` | ✅ | Answers, posts |

### How OAuth Connections Work

1. **User connects** via the frontend (OAuth flow → redirect → token exchange)
2. **Tokens stored** in `social_connections` table (encrypted)
3. **AI tools** resolve credentials via `social_connection_service.resolve_connection()`
4. **Token refresh** happens automatically for platforms with refresh tokens

### Setting Up OAuth Apps

For each platform you want to support, you need to register an OAuth App/Client:

**Example: LinkedIn**
1. Go to [LinkedIn Developer Portal](https://www.linkedin.com/developers/)
2. Create an App → note Client ID and Client Secret
3. Set redirect URI: `https://your-domain.com/api/social-connections/callback/linkedin`
4. Request necessary products (Share on LinkedIn, Marketing, etc.)

**Example: Twitter/X**
1. Go to [Twitter Developer Portal](https://developer.twitter.com/)
2. Create a Project & App → get API Key, API Secret, Bearer Token
3. Enable OAuth 2.0 with PKCE
4. Set callback URL: `https://your-domain.com/api/social-connections/callback/twitter`

> **Management API:** `POST /api/social-connections` — connect accounts, `GET /api/social-connections` — list connections

---

## 16. Redis — Session Caching

Redis is used for **voice session caching** (read-through cache with 5-minute TTL) and **API gateway rate limiting**.

### 16.1: Install Redis

```bash
# Ubuntu/Debian
sudo apt install redis-server
sudo systemctl enable redis-server

# Or Docker
docker run -d --name redis -p 6379:6379 redis:7-alpine
```

### 16.2: Set Environment Variable

```bash
export REDIS_URL="redis://localhost:6379"
```

> **Used by:**
> - `voice/session_manager.py` — Voice/WhatsApp session caching
> - `gateway/config.py` — API rate limiting

> **Optional:** Redis is not required for the platform to function. If unavailable, session management falls back to PostgreSQL-only mode (suitable for <50 concurrent sessions).

---

## 17. Playwright — Headless Browser

Playwright is used by AI agents for browser-based interactions (navigation, screenshots, scraping rendered content).

### 17.1: Install

```bash
pip install playwright
playwright install chromium
```

No API keys or credentials needed — Playwright runs locally on the server.

> **Used by:** `ai/tools/browser_tool.py` — HeadlessBrowserTool

> **Note:** Each browser action creates an ephemeral, isolated browser context that is automatically destroyed after execution. No persistent cookies or state.

---

## 18. Complete Environment Variables Reference

> **Policy:** Only core application settings go in `.env`. All third-party service credentials (Twilio, Tata Tele, Razorpay, Firecrawl, Google CSE, SerpAPI, SMTP, AI models) are stored in the **Integration Registry** database table.

```bash
# ============================================================
# REQUIRED — Core Application
# ============================================================
DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/hirebuddha"
REDIS_URL="redis://localhost:6379"
SECRET_KEY="your-jwt-secret-key"
ENCRYPTION_MASTER_KEY="your-32-byte-encryption-key"

# ============================================================
# REQUIRED — GCP (Vertex AI for Google/Anthropic models)
# ============================================================
GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"

# ============================================================
# OPTIONAL — Frontend URL (for email links)
# ============================================================
FRONTEND_URL="https://app.hirebuddha.com"

# ============================================================
# OPTIONAL — Streaming Service
# ============================================================
STREAMING_HOST="localhost:8002"
STREAMING_PROTOCOL="ws"
```

> **All other credentials** (Twilio, Tata Tele, Razorpay, Firecrawl, Google CSE, SerpAPI, SMTP, AI model keys) are stored in the **Integration Registry** table with encrypted API keys. Social media OAuth tokens are stored in the **Social Connections** table. Agent email credentials are stored in the **Email Connections** table.

