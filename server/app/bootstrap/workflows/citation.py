"""Short-transaction citation resolution workflow."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import math
from uuid import UUID

from app.bootstrap.adapters.citation_provider import CitationMetadataProvider
from app.bootstrap.capabilities import ApplicationCapabilities
from app.modules.papers.application.citations import (
    CitationMetadataPatch,
    build_citation_result,
    normalize_citation_metadata_patch,
)
from app.modules.papers.application.contracts.citation import (
    CitationData,
    CitationMethod,
    CitationResult,
    CitationStep,
)
from app.modules.papers.domain.citations import (
    STYLE_DISPLAY_NAMES,
    CitationFields,
    missing_required_fields,
    normalize_style,
)
from app.modules.papers.application.contracts.search import PaperCollection
from app.shared.application import (
    Actor,
    ApplicationExecutor,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
)

logger = logging.getLogger(__name__)


_PATCH_FIELD_NAMES = ("doi", "journal", "publisher", "publish_date")


def _patch_values(patch: CitationMetadataPatch) -> dict[str, str]:
    return {
        field_name: value
        for field_name in _PATCH_FIELD_NAMES
        if (value := getattr(patch, field_name)) is not None
    }


def _patch_has_values(patch: CitationMetadataPatch) -> bool:
    return bool(_patch_values(patch))


def _normalized_confidence(value: float | None) -> float | None:
    if value is None or not math.isfinite(value) or not 0 <= value <= 1:
        return None
    return value


def _merge_fields(
    fields: CitationFields,
    patch: CitationMetadataPatch,
) -> CitationFields:
    return CitationFields(
        title=fields.title,
        authors=list(fields.authors),
        publish_date=fields.publish_date or patch.publish_date,
        journal=fields.journal or patch.journal,
        publisher=fields.publisher or patch.publisher,
        doi=fields.doi or patch.doi,
    )


def _combine_patches(
    first: CitationMetadataPatch,
    second: CitationMetadataPatch,
) -> CitationMetadataPatch:
    first_provenance = first.field_provenance or {}
    second_provenance = second.field_provenance or {}
    provenance = {**first_provenance, **second_provenance} or None
    return CitationMetadataPatch(
        doi=first.doi or second.doi,
        journal=first.journal or second.journal,
        publisher=first.publisher or second.publisher,
        publish_date=first.publish_date or second.publish_date,
        field_provenance=provenance,
    )


@dataclass(frozen=True, slots=True)
class CitationResolutionPlan:
    """Persistence-free provider result ready for one atomic application write."""

    document_id: UUID
    project_id: UUID | None
    paper_collection: PaperCollection | None
    anchor_document_id: UUID | None
    canonical_style: str
    style_display: str
    initial_fields: CitationFields | None
    patch: CitationMetadataPatch
    planned_method: CitationMethod
    deterministic_field_names: tuple[str, ...]
    agentic_field_names: tuple[str, ...]
    confidence: float | None
    steps: tuple[CitationStep, ...]


class CitationWorkflow:
    def __init__(
        self,
        *,
        executor: ApplicationExecutor[ApplicationCapabilities],
        provider: CitationMetadataProvider,
        operation_factory: OperationContextFactory,
    ) -> None:
        self._executor = executor
        self._provider = provider
        self._operation_factory = operation_factory

    def run(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
        style: str = "APA",
        project_id: UUID | None = None,
        paper_collection: PaperCollection | None = None,
        anchor_document_id: UUID | None = None,
    ) -> CitationResult:
        plan = self.prepare(
            actor=actor,
            operation=operation,
            document_id=document_id,
            style=style,
            project_id=project_id,
            paper_collection=paper_collection,
            anchor_document_id=anchor_document_id,
        )
        if not _patch_has_values(plan.patch):
            return self.complete(plan, fields=plan.initial_fields)
        return self._executor.command(
            lambda capabilities: self.apply_prepared(
                capabilities,
                actor=actor,
                operation=operation,
                plan=plan,
            )
        )

    def prepare(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
        style: str = "APA",
        project_id: UUID | None = None,
        paper_collection: PaperCollection | None = None,
        anchor_document_id: UUID | None = None,
    ) -> CitationResolutionPlan:
        """Perform authorization and provider I/O without committing metadata."""

        if paper_collection is not None:
            self._executor.query(
                lambda capabilities: capabilities.paper_collection_access(
                    actor=actor,
                    collection=paper_collection,
                    document_id=document_id,
                    anchor_document_id=anchor_document_id,
                )
            )
        canonical = normalize_style(style)
        display = STYLE_DISPLAY_NAMES[canonical]
        steps: list[CitationStep] = []
        fields = self._read(
            actor=actor,
            document_id=document_id,
            project_id=project_id,
        )
        if fields is None:
            return CitationResolutionPlan(
                document_id=document_id,
                project_id=project_id,
                paper_collection=paper_collection,
                anchor_document_id=anchor_document_id,
                canonical_style=canonical,
                style_display=display,
                initial_fields=None,
                patch=CitationMetadataPatch(),
                planned_method="not_found",
                deterministic_field_names=(),
                agentic_field_names=(),
                confidence=None,
                steps=(
                    CitationStep(
                        kind="check",
                        detail="Paper not found or access denied.",
                    ),
                ),
            )

        initial_fields = fields
        missing = missing_required_fields(fields, canonical)
        steps.append(
            CitationStep(
                kind="check",
                detail=f"Fields needed for {display}: {missing or 'none missing'}.",
                data={"missing": missing},
            )
        )
        if not missing:
            return CitationResolutionPlan(
                document_id=document_id,
                project_id=project_id,
                paper_collection=paper_collection,
                anchor_document_id=anchor_document_id,
                canonical_style=canonical,
                style_display=display,
                initial_fields=initial_fields,
                patch=CitationMetadataPatch(),
                planned_method="cached",
                deterministic_field_names=(),
                agentic_field_names=(),
                confidence=None,
                steps=tuple(steps),
            )

        try:
            deterministic = self._provider.deterministic(
                actor=actor,
                operation=operation,
                fields=fields,
            )
        except Exception:
            logger.exception(
                "citation.metadata_lookup.failed",
                extra={"document_id": str(document_id)},
            )
            deterministic = None
        deterministic_patch = CitationMetadataPatch()
        deterministic_field_names: tuple[str, ...] = ()
        if deterministic is not None and deterministic.filled_fields:
            deterministic_patch, dropped_fields = normalize_citation_metadata_patch(
                deterministic.patch
            )
            if dropped_fields:
                logger.warning(
                    "citation.provider_fields_invalid",
                    extra={"dropped_fields": dropped_fields, "stage": "deterministic"},
                )
            deterministic_field_names = tuple(
                sorted(_patch_values(deterministic_patch))
            )
            fields = _merge_fields(fields, deterministic_patch)
        missing = missing_required_fields(fields, canonical)
        steps.append(
            CitationStep(
                kind="deterministic",
                detail=(
                    "After deterministic metadata lookup, still missing: "
                    f"{missing or 'none'}."
                ),
                data={
                    "missing": missing,
                    "doi": fields.doi,
                    "journal": fields.journal,
                    "publisher": fields.publisher,
                    "identity_mismatch": bool(
                        deterministic and deterministic.identity_mismatch
                    ),
                },
            )
        )
        if not missing:
            return CitationResolutionPlan(
                document_id=document_id,
                project_id=project_id,
                paper_collection=paper_collection,
                anchor_document_id=anchor_document_id,
                canonical_style=canonical,
                style_display=display,
                initial_fields=initial_fields,
                patch=deterministic_patch,
                planned_method="deterministic",
                deterministic_field_names=deterministic_field_names,
                agentic_field_names=(),
                confidence=None,
                steps=tuple(steps),
            )

        if deterministic is not None and deterministic.identity_mismatch:
            return CitationResolutionPlan(
                document_id=document_id,
                project_id=project_id,
                paper_collection=paper_collection,
                anchor_document_id=anchor_document_id,
                canonical_style=canonical,
                style_display=display,
                initial_fields=initial_fields,
                patch=deterministic_patch,
                planned_method="partial",
                deterministic_field_names=deterministic_field_names,
                agentic_field_names=(),
                confidence=None,
                steps=tuple(steps),
            )

        recovered = self._provider.agentic(
            actor=actor,
            fields=fields,
            missing_fields=missing,
            steps=steps,
        )
        agentic_patch = CitationMetadataPatch()
        agentic_field_names: tuple[str, ...] = ()
        if recovered.filled_fields:
            agentic_patch, dropped_fields = normalize_citation_metadata_patch(
                recovered.patch
            )
            if dropped_fields:
                logger.warning(
                    "citation.provider_fields_invalid",
                    extra={"dropped_fields": dropped_fields, "stage": "agentic"},
                )
            agentic_field_names = tuple(sorted(_patch_values(agentic_patch)))
            fields = _merge_fields(fields, agentic_patch)
        combined_patch = _combine_patches(deterministic_patch, agentic_patch)
        confidence = _normalized_confidence(recovered.confidence)
        if recovered.confidence is not None and confidence is None:
            logger.warning("citation.provider_confidence_invalid")
        return CitationResolutionPlan(
            document_id=document_id,
            project_id=project_id,
            paper_collection=paper_collection,
            anchor_document_id=anchor_document_id,
            canonical_style=canonical,
            style_display=display,
            initial_fields=initial_fields,
            patch=combined_patch,
            planned_method="agentic" if agentic_field_names else "partial",
            deterministic_field_names=deterministic_field_names,
            agentic_field_names=agentic_field_names,
            confidence=confidence,
            steps=tuple(steps),
        )

    def apply_prepared(
        self,
        capabilities: ApplicationCapabilities,
        *,
        actor: Actor,
        operation: OperationContext,
        plan: CitationResolutionPlan,
    ) -> CitationResult:
        """Apply a prepared patch inside the caller's existing transaction."""

        if plan.paper_collection is not None:
            capabilities.paper_collection_access(
                actor=actor,
                collection=plan.paper_collection,
                document_id=plan.document_id,
                anchor_document_id=plan.anchor_document_id,
            )
        current = capabilities.citations.read(
            actor=actor,
            document_id=plan.document_id,
            project_id=plan.project_id,
        )
        if current is None:
            return self.complete(plan, fields=None)
        if _patch_has_values(plan.patch):
            apply_operation = self._operation_factory.child(
                operation,
                initiated_by=OperationInitiator.SYSTEM,
            )
            current = capabilities.citations.apply_missing(
                actor=actor,
                operation=apply_operation,
                document_id=plan.document_id,
                project_id=plan.project_id,
                patch=plan.patch,
            )
        return self.complete(plan, fields=current)

    @staticmethod
    def complete(
        plan: CitationResolutionPlan,
        *,
        fields: CitationFields | None,
    ) -> CitationResult:
        """Build the canonical result from facts actually visible after application."""

        if fields is None:
            return CitationResult(
                document_id=str(plan.document_id),
                preferred_style=plan.canonical_style,
                style_display=plan.style_display,
                data=CitationData(document_id=str(plan.document_id)),
                method="not_found",
                steps=list(plan.steps),
            )
        missing = missing_required_fields(fields, plan.canonical_style)
        initial = plan.initial_fields or CitationFields()
        filled_fields = {
            field_name: getattr(fields, field_name)
            for field_name in plan.agentic_field_names
            if getattr(initial, field_name) is None
            and getattr(fields, field_name) is not None
        }
        method: CitationMethod
        if plan.planned_method == "cached":
            method = "cached"
        elif filled_fields:
            method = "agentic"
        elif plan.deterministic_field_names and not missing:
            method = "deterministic"
        else:
            method = "partial"
        steps = list(plan.steps)
        if filled_fields:
            steps.append(
                CitationStep(
                    kind="write_back",
                    detail=(
                        f"Wrote back {list(filled_fields)} "
                        f"(confidence {plan.confidence})."
                    ),
                    data=filled_fields,
                )
            )
        return build_citation_result(
            document_id=plan.document_id,
            canonical_style=plan.canonical_style,
            style_display=plan.style_display,
            fields=fields,
            method=method,
            missing_fields=missing,
            filled_fields=filled_fields,
            confidence=plan.confidence,
            steps=steps,
        )

    def _read(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None,
    ) -> CitationFields | None:
        return self._executor.query(
            lambda capabilities: capabilities.citations.read(
                actor=actor,
                document_id=document_id,
                project_id=project_id,
            )
        )


__all__ = ["CitationResolutionPlan", "CitationWorkflow"]
