"""Framework-independent application contracts."""

from .actor import Actor
from .avatar import AvatarReference
from .clock import Clock
from .cursors import SignedCursorCodec
from .executor import ApplicationExecutor
from .error_envelope import ErrorEnvelope
from .operation_context import (
    CliOrigin,
    ConversationOrigin,
    CredentialKind,
    CredentialRef,
    HttpOrigin,
    JobOrigin,
    McpOrigin,
    OAuthCallbackOrigin,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
    OperationOrigin,
    OperationTrace,
    RequestReference,
    SchedulerOrigin,
    WebhookOrigin,
)

__all__ = [
    "Actor",
    "ApplicationExecutor",
    "AvatarReference",
    "ErrorEnvelope",
    "Clock",
    "CliOrigin",
    "ConversationOrigin",
    "CredentialKind",
    "CredentialRef",
    "HttpOrigin",
    "JobOrigin",
    "McpOrigin",
    "OAuthCallbackOrigin",
    "OperationContext",
    "OperationContextFactory",
    "OperationInitiator",
    "OperationOrigin",
    "OperationTrace",
    "RequestReference",
    "SchedulerOrigin",
    "SignedCursorCodec",
    "WebhookOrigin",
]
