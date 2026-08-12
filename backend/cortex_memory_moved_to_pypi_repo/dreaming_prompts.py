"""
dreaming_prompts.py — LLM Prompt Templates for the Dreaming Engine

Three prompts for the three-phase learning pipeline:
  Phase 1: Observation extraction from episodes
  Phase 2: Pattern recognition across observations
  Phase 3: Intelligence distillation from patterns
"""

OBSERVATION_EXTRACTION_PROMPT = """You are analyzing execution history for an AI agent.
Given a batch of recent execution episodes, extract concrete OBSERVATIONS about:

1. TOOL PATTERNS: Which tools are used, in what order, and their effectiveness
2. SUCCESS FACTORS: What conditions correlate with successful outcomes
3. FAILURE PATTERNS: What conditions or sequences lead to failures
4. COST PATTERNS: What drives cost up or down
5. TIME PATTERNS: What affects execution time

For each observation, provide:
- title: A concise name (max 100 chars)
- description: A detailed description (max 500 chars)
- confidence: 0.0 to 1.0 indicating how confident this observation is
- source_episodes: List of episode IDs that support this observation

Return as JSON array: [{"title": "...", "description": "...", "confidence": 0.8, "source_episodes": ["..."]}]
Only return the JSON array, no other text."""

PATTERN_RECOGNITION_PROMPT = """You are identifying patterns from multiple observations.
Given a cluster of related observations, synthesize them into a PATTERN:

A pattern is a recurring behavior or correlation that appears across multiple observations.
It should be generalizable and actionable.

Return as JSON: {
  "title": "...",
  "description": "...",
  "strength": 0.0 to 1.0,
  "success_correlation": 0.0 to 1.0,
  "actionability": "The pattern suggests..."
}
Only return the JSON object, no other text."""

INTELLIGENCE_DISTILLATION_PROMPT = """You are distilling patterns into actionable intelligence rules.
Given strong, validated patterns, create RULES the agent should follow:

Types of rules:
- instruction: A specific, concrete action to take or avoid
- strategy: A high-level approach or workflow template
- preference: A learned user/context preference

IMPORTANT: Do NOT duplicate existing rules. Check the provided list of existing rules.

Return as JSON array: [{"type": "instruction|strategy|preference", "title": "...",
"description": "...", "confidence": 0.0-1.0, "applicability_conditions": ["..."]}]
Only return the JSON array, no other text."""
