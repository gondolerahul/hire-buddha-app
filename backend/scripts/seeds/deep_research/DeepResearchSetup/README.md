# Deep Research Setup
## CORTEX Memory System Test — World-Class Deep Research Process

This folder contains the complete setup for the **Deep Research** hierarchical entity system
designed to stress-test the CORTEX Memory Architecture.

## Quick Start

### 1. Set your auth token

```bash
# Get your JWT token from the browser (DevTools → Application → Local Storage → token)
export AUTH_TOKEN="your_jwt_token_here"
```

### 2. Create all entities

```bash
# Dry run — see what will be created without making API calls
python create_entities.py --dry-run

# Create all 15 entities
python create_entities.py --token "$AUTH_TOKEN"

# Create entities AND trigger a test execution
python create_entities.py --token "$AUTH_TOKEN" --execute

# Custom base URL (e.g. local development)
python create_entities.py --base-url http://localhost:8000/api/v1 --token "$AUTH_TOKEN"
```

### 3. Trigger execution separately

```bash
python trigger_execution.py --token "$AUTH_TOKEN"

# Custom topic
python trigger_execution.py --token "$AUTH_TOKEN" --topic "The current state of quantum computing in 2026"
```

## Files

| File | Description |
|------|-------------|
| `DESIGN.md` | Full architecture design document |
| `create_entities.py` | Main script — creates all 15 entities via API |
| `trigger_execution.py` | Trigger a Deep Research execution run |
| `entity_ids.json` | Auto-generated after creation — entity UUID mapping |
| `README.md` | This file |

## Entity Hierarchy (15 Entities)

```
PROCESS: 🔬 Deep Research
├── AGENT: Research Director
│   ├── SKILL: Query Decomposer
│   ├── SKILL: Source Discoverer
│   │   └── ACTION: Web Search
│   ├── SKILL: Source Analyzer
│   │   ├── ACTION: Page Scraper
│   │   └── ACTION: Content Extractor
│   └── SKILL: Fact Verifier
│       └── ACTION: Fact Checker
└── AGENT: Report Synthesizer
    └── SKILL: Knowledge Synthesizer
        ├── ACTION: Outline Generator
        ├── ACTION: Section Writer
        └── ACTION: PDF Exporter
```

## Test Topic

Default test topic:
> *"Impact of generative AI on the creative industries: economics, employment, and intellectual property"*

## What This Tests in CORTEX

| Feature | How It's Tested |
|---------|----------------|
| Tree Creation | Fresh CORTEX tree per execution |
| NAVIGATE | Agent navigates Knowledge/Working/Output subtrees |
| READ | Cross-referencing previously written findings |
| WRITE | Every source analysis writes nodes to tree |
| RECURSE | Process spawns child AGENT runs |
| CHECKPOINT | Auto-checkpoints after research waves |
| AWAIT_CHILDREN | Process waits for Research Director |
| ASSEMBLE | Report Synthesizer assembles final output |
| Context Budget | Long scrape+analyze loops trigger compaction |
| Resume | Multi-hour runs resume from CORTEX cursor |
