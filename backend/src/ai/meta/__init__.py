"""
meta — Meta-Agent V2 Infrastructure for HireBuddha Platform.

This package provides the foundation for a Meta-Agent that can:
  1. Understand the full platform capability surface (tools, models, schemas,
     and behavioral execution semantics via compiled annotations)
  2. Search existing agent registry for reuse/adaptation candidates using
     a four-phase scoring pipeline (structural, IO contract, semantic, traces)
  3. Synthesize new agent definitions (HierarchicalEntity payloads)
  4. Validate and test-execute generated agents
  5. Enforce anti-sprawl governance with hard gates and semantic deduplication

Architecture (V2):
  The Meta-Agent is a single HierarchicalEntity (type=AGENT) using REACT
  reasoning mode with 5 meta-tools. It replaces the V1 PROCESS hierarchy
  (4 child AGENTs + orchestrator) with a single-entity design that is
  cheaper (~60% cost reduction), more reliable (no context propagation
  fragility), and naturally handles conditional branching via REACT.
"""
