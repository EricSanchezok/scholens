"""Canonical model-tool catalog shared by every inbound agent transport."""

from .catalog import ToolCatalog, ToolProfile
from .contracts import (
    DEFAULT_TOOL_OUTPUT_BYTES,
    DocumentSourceCandidate,
    ExternalSourceCandidate,
    ExternalSourceProvenance,
    ToolAccess,
    ToolBehavior,
    ToolConfirmationPolicy,
    ToolExecutionContext,
    ToolDefinition,
    ToolExecutionKind,
    ToolOutcome,
    ToolOutcomeFinalizer,
    ToolOutcomeProjector,
    ToolResourceLink,
    ToolSourceCandidate,
    ToolStructuredResult,
)
from .dispatcher import ToolDispatcher
from .results import serialize_tool_success

__all__ = [
    "DEFAULT_TOOL_OUTPUT_BYTES",
    "DocumentSourceCandidate",
    "ExternalSourceCandidate",
    "ExternalSourceProvenance",
    "ToolAccess",
    "ToolBehavior",
    "ToolCatalog",
    "ToolDefinition",
    "ToolConfirmationPolicy",
    "ToolDispatcher",
    "ToolExecutionContext",
    "ToolExecutionKind",
    "ToolOutcome",
    "ToolOutcomeFinalizer",
    "ToolOutcomeProjector",
    "ToolResourceLink",
    "ToolProfile",
    "ToolSourceCandidate",
    "ToolStructuredResult",
    "serialize_tool_success",
]
