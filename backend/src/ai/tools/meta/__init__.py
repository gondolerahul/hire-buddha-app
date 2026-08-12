"""
meta tools — Custom tools for the Meta-Agent.

These tools are registered as tenant-scoped tools for the Meta-Agent's
company_id via ToolRegistry.register_tenant_tool().

Available meta-tools:
  meta_registry_search   — Search existing agent registry for reuse candidates
  meta_schema_validator   — Validate entity JSON against platform schemas
  meta_entity_creator     — Create/version HierarchicalEntity definitions
  meta_entity_executor    — Trigger test executions of generated agents
  meta_platform_introspect — Query platform schema (tools, models, constraints)
"""

from src.ai.tools.meta.registry_search import MetaRegistrySearchTool
from src.ai.tools.meta.schema_validator import MetaSchemaValidatorTool
from src.ai.tools.meta.entity_creator import MetaEntityCreatorTool
from src.ai.tools.meta.entity_executor import MetaEntityExecutorTool
from src.ai.tools.meta.platform_introspect import MetaPlatformIntrospectTool
from src.ai.tools.meta.spec_critic import MetaSpecCriticTool
from src.ai.tools.meta.agent_introspect import AgentIntrospectTool
from src.ai.tools.meta.agent_reflect import AgentReflectTool
from src.ai.tools.meta.tool_synthesis import ToolSynthesisTool

__all__ = [
    "MetaRegistrySearchTool",
    "MetaSchemaValidatorTool",
    "MetaEntityCreatorTool",
    "MetaEntityExecutorTool",
    "MetaPlatformIntrospectTool",
    "MetaSpecCriticTool",
    "AgentIntrospectTool",
    "AgentReflectTool",
    "ToolSynthesisTool",
]
