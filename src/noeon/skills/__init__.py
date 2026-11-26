"""Noeon skill universe: catalog, discovery, security and execution.

The modules in this package implement the skill layer on top of the existing
Noeon contracts. They do not reimplement DeerFlow or OpenHands: DeerFlow keeps
orchestration and OpenHands keeps code execution.
"""

from .agents import AgentSkillManager, Assignment
from .dependencies import DependencyStatus, SkillDependencyManager
from .discovery import EmbeddingProvider, SkillDiscoveryEngine, SkillMatch
from .evaluation import evaluate, evaluation_summary
from .executor import ExecutionPolicy, ExecutionResult, SkillExecutor
from .learning import DraftResult, MissionEvidence, SkillLearningEngine
from .loader import SkillContext, SkillLoader, estimate_tokens
from .manifest import build_record
from .mcp import MCPManager, MCPServer, MCPStatus
from .model import (
    InstallationStatus,
    Origin,
    SecurityDecision,
    SkillFinding,
    SkillRecord,
    SkillSource,
    SourceReport,
    ValidationStatus,
    skill_id_for,
)
from .registry import SkillRegistry
from .runtime import MissionSkillPlan, SkillUniverse, build_universe, plan_mission, select_roles
from .security import SecurityReport, scan_skill, scan_text
from .sources import GitHubClient, LicenseInfo, SourceFetchError, read_sources, write_lock
from .sync import InstallResult, SkillSyncEngine
from .taxonomy import CATEGORIES, ROLE_PROFILES, classify, profile_for
from .tools import ToolRegistry, ToolSpec, ToolStatus
from .tools import default_registry as default_tool_registry
from .validate import ValidationOutcome, normalize_license, validate

__all__ = [
    "CATEGORIES",
    "ROLE_PROFILES",
    "AgentSkillManager",
    "Assignment",
    "DependencyStatus",
    "DraftResult",
    "EmbeddingProvider",
    "ExecutionPolicy",
    "ExecutionResult",
    "GitHubClient",
    "InstallResult",
    "InstallationStatus",
    "LicenseInfo",
    "MCPManager",
    "MCPServer",
    "MCPStatus",
    "MissionEvidence",
    "MissionSkillPlan",
    "Origin",
    "SecurityDecision",
    "SecurityReport",
    "SkillContext",
    "SkillDependencyManager",
    "SkillDiscoveryEngine",
    "SkillExecutor",
    "SkillFinding",
    "SkillLearningEngine",
    "SkillLoader",
    "SkillMatch",
    "SkillRecord",
    "SkillRegistry",
    "SkillSource",
    "SkillSyncEngine",
    "SkillUniverse",
    "SourceFetchError",
    "SourceReport",
    "ToolRegistry",
    "ToolSpec",
    "ToolStatus",
    "ValidationOutcome",
    "ValidationStatus",
    "build_record",
    "build_universe",
    "classify",
    "default_tool_registry",
    "estimate_tokens",
    "evaluate",
    "evaluation_summary",
    "normalize_license",
    "plan_mission",
    "profile_for",
    "read_sources",
    "scan_skill",
    "scan_text",
    "select_roles",
    "skill_id_for",
    "validate",
    "write_lock",
]
