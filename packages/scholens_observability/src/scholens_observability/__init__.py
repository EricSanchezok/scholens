"""Business-agnostic observability primitives shared by Scholens services."""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scholens_observability.context import (
        ObservabilityContext as ObservabilityContext,
        bind_context as bind_context,
        current_context as current_context,
        reset_context as reset_context,
        set_context as set_context,
        update_context as update_context,
    )
    from scholens_observability.diagnostics import (
        BufferedS3DiagnosticSnapshotRecorder as BufferedS3DiagnosticSnapshotRecorder,
        DiagnosticSnapshot as DiagnosticSnapshot,
        DiagnosticSnapshotRecorder as DiagnosticSnapshotRecorder,
        NullDiagnosticSnapshotRecorder as NullDiagnosticSnapshotRecorder,
        SensitiveValue as SensitiveValue,
        build_snapshot as build_snapshot,
        diagnostic_id as diagnostic_id,
        should_sample_success as should_sample_success,
    )
    from scholens_observability.logging import (
        configure_logging as configure_logging,
        log_event as log_event,
    )
    from scholens_observability.metrics import (
        add_counter as add_counter,
        record_histogram as record_histogram,
    )
    from scholens_observability.tracing import (
        configure_telemetry as configure_telemetry,
        instrumented_span as instrumented_span,
        shutdown_telemetry as shutdown_telemetry,
    )


# Keep command entrypoints independent of optional runtime stacks.
_EXPORTS = {
    name: module
    for module, names in {
        "scholens_observability.context": (
            "ObservabilityContext",
            "bind_context",
            "current_context",
            "reset_context",
            "set_context",
            "update_context",
        ),
        "scholens_observability.diagnostics": (
            "BufferedS3DiagnosticSnapshotRecorder",
            "DiagnosticSnapshot",
            "DiagnosticSnapshotRecorder",
            "NullDiagnosticSnapshotRecorder",
            "SensitiveValue",
            "build_snapshot",
            "diagnostic_id",
            "should_sample_success",
        ),
        "scholens_observability.logging": (
            "configure_logging",
            "log_event",
        ),
        "scholens_observability.metrics": (
            "add_counter",
            "record_histogram",
        ),
        "scholens_observability.tracing": (
            "configure_telemetry",
            "instrumented_span",
            "shutdown_telemetry",
        ),
    }.items()
    for name in names
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(name)
    value = getattr(import_module(module), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
