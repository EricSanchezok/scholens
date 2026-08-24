"""Public, transport-neutral reading activity contracts."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.modules.reading_activity.domain import (
    ACTIVE_READING_DEFINITION_VERSION,
    MAX_READING_SESSION_DURATION_MS,
    MAX_READING_SESSION_HOUR_BUCKETS,
    PAGE_VERTICAL_SEGMENT_COUNT,
)
from app.shared.domain import JsonValue


class ReadingViewMode(StrEnum):
    PDF = "pdf"
    REFLOW = "reflow"


class ReadingInsightsRange(StrEnum):
    SEVEN_DAYS = "7d"
    THIRTY_DAYS = "30d"
    NINETY_DAYS = "90d"
    YEAR = "365d"
    ALL = "all"


class ReadingExportFormat(StrEnum):
    JSON = "json"
    CSV = "csv"


class ProjectActivityKind(StrEnum):
    PAPER_ADDED = "paper_added"
    MEMBER_JOINED = "member_joined"
    ANNOTATION_CREATED = "annotation_created"
    OUTPUT_CREATED = "output_created"
    DISCUSSION_MESSAGE_POSTED = "discussion_message_posted"
    DISCUSSION_RESOLVED = "discussion_resolved"


class ReadingActivityPreferencesUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recording_enabled: bool
    contribute_anonymous_project_aggregates: bool


class ReadingActivityPreferencesResponse(BaseModel):
    recording_enabled: bool = True
    contribute_anonymous_project_aggregates: bool = True


class ReadingSessionStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    project_id: UUID | None = None
    view_mode: ReadingViewMode
    started_at: datetime
    time_zone: str = Field(min_length=1, max_length=64)
    metric_definition_version: str = Field(
        default=ACTIVE_READING_DEFINITION_VERSION,
        min_length=1,
        max_length=64,
    )

    @field_validator("started_at")
    @classmethod
    def require_aware_started_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("started_at must include a time zone")
        return value


class ReadingPageSnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_number: int = Field(ge=1, le=10_000)
    visible_ms: int = Field(ge=0, le=MAX_READING_SESSION_DURATION_MS)
    active_ms: int = Field(ge=0, le=MAX_READING_SESSION_DURATION_MS)
    visit_count: int = Field(ge=0, le=1_000_000)
    vertical_segments_ms: list[int] = Field(
        min_length=PAGE_VERTICAL_SEGMENT_COUNT,
        max_length=PAGE_VERTICAL_SEGMENT_COUNT,
    )

    @model_validator(mode="after")
    def validate_page_snapshot(self) -> ReadingPageSnapshotRequest:
        if self.active_ms > self.visible_ms:
            raise ValueError("page active_ms cannot exceed visible_ms")
        if any(value < 0 for value in self.vertical_segments_ms):
            raise ValueError("vertical segment durations cannot be negative")
        if sum(self.vertical_segments_ms) != self.active_ms:
            raise ValueError("vertical segment durations must equal page active_ms")
        return self


class ReadingHourSnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bucket_start: datetime
    visible_ms: int = Field(ge=0, le=MAX_READING_SESSION_DURATION_MS)
    active_ms: int = Field(ge=0, le=MAX_READING_SESSION_DURATION_MS)

    @field_validator("bucket_start")
    @classmethod
    def require_utc_hour(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("bucket_start must use UTC")
        normalized = value.astimezone(timezone.utc)
        if any((normalized.minute, normalized.second, normalized.microsecond)):
            raise ValueError("bucket_start must be aligned to a UTC hour")
        return normalized

    @model_validator(mode="after")
    def validate_hour_snapshot(self) -> ReadingHourSnapshotRequest:
        if self.active_ms > self.visible_ms:
            raise ValueError("hour active_ms cannot exceed visible_ms")
        return self


class ReadingSessionSnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1, le=2_147_483_647)
    visible_ms: int = Field(ge=0, le=MAX_READING_SESSION_DURATION_MS)
    active_ms: int = Field(ge=0, le=MAX_READING_SESSION_DURATION_MS)
    last_seen_at: datetime
    ended_at: datetime | None = None
    hours: list[ReadingHourSnapshotRequest] = Field(
        min_length=1,
        max_length=MAX_READING_SESSION_HOUR_BUCKETS,
    )
    pages: list[ReadingPageSnapshotRequest] = Field(
        default_factory=list, max_length=100
    )

    @field_validator("last_seen_at", "ended_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("reading timestamps must include a time zone")
        return value

    @model_validator(mode="after")
    def validate_snapshot(self) -> ReadingSessionSnapshotRequest:
        if self.active_ms > self.visible_ms:
            raise ValueError("active_ms cannot exceed visible_ms")
        if self.ended_at is not None and self.ended_at < self.last_seen_at:
            raise ValueError("ended_at cannot precede last_seen_at")
        if len({page.page_number for page in self.pages}) != len(self.pages):
            raise ValueError("pages must contain unique page numbers")
        if len({hour.bucket_start for hour in self.hours}) != len(self.hours):
            raise ValueError("hours must contain unique UTC buckets")
        last_bucket = self.last_seen_at.astimezone(timezone.utc).replace(
            minute=0,
            second=0,
            microsecond=0,
        )
        if any(hour.bucket_start > last_bucket for hour in self.hours):
            raise ValueError("hour bucket cannot follow last_seen_at")
        if sum(hour.visible_ms for hour in self.hours) != self.visible_ms:
            raise ValueError("hour visible_ms must equal session visible_ms")
        if sum(hour.active_ms for hour in self.hours) != self.active_ms:
            raise ValueError("hour active_ms must equal session active_ms")
        if sum(page.active_ms for page in self.pages) > self.active_ms:
            raise ValueError("page active_ms cannot exceed session active_ms")
        if sum(page.visible_ms for page in self.pages) > self.visible_ms:
            raise ValueError("page visible_ms cannot exceed session visible_ms")
        return self


class ReadingSessionResponse(BaseModel):
    id: UUID
    document_id: UUID
    project_id: UUID | None
    view_mode: ReadingViewMode
    time_zone: str
    metric_definition_version: str
    revision: int = Field(ge=0, le=2_147_483_647)
    visible_ms: int
    active_ms: int
    started_at: datetime
    last_seen_at: datetime
    ended_at: datetime | None
    project_contribution_enabled: bool
    page_detail_available: bool


class ReadingSummaryResponse(BaseModel):
    active_ms: int = Field(ge=0)
    visible_ms: int = Field(ge=0)
    session_count: int = Field(ge=0)
    active_days: int = Field(ge=0)
    substantive_pages: int | None = Field(default=None, ge=0)
    coverage_percent: float | None = Field(default=None, ge=0, le=100)


class ReadingTrendPointResponse(BaseModel):
    date: date
    active_ms: int = Field(ge=0)
    visible_ms: int = Field(ge=0)
    session_count: int = Field(ge=0)


class ReadingPageInsightResponse(BaseModel):
    page_number: int = Field(ge=1)
    active_ms: int = Field(ge=0)
    visible_ms: int = Field(ge=0)
    visit_count: int = Field(ge=0)
    vertical_segments_ms: list[int] = Field(
        min_length=PAGE_VERTICAL_SEGMENT_COUNT,
        max_length=PAGE_VERTICAL_SEGMENT_COUNT,
    )
    annotation_count: int = Field(default=0, ge=0)


class PaperInsightsResponse(BaseModel):
    document_id: UUID
    page_count: int | None = Field(default=None, ge=1)
    metric_definition_version: str = ACTIVE_READING_DEFINITION_VERSION
    reading_data_since: datetime | None
    activity_history_complete_since: datetime | None
    time_zone: str
    range: ReadingInsightsRange
    summary: ReadingSummaryResponse
    trend: list[ReadingTrendPointResponse]
    pages: list[ReadingPageInsightResponse]


class ProjectMineInsightsResponse(BaseModel):
    reading: ReadingSummaryResponse
    papers_with_activity: int = Field(ge=0)
    private_conversation_count: int = Field(ge=0)
    annotation_count: int = Field(ge=0)


class ProjectTeamInsightsResponse(BaseModel):
    anonymous_reading_available: bool
    active_ms: int | None = Field(default=None, ge=0)
    visible_ms: int | None = Field(default=None, ge=0)
    papers_with_activity: int | None = Field(default=None, ge=0)
    substantive_pages: int | None = Field(default=None, ge=0)
    papers_added: int = Field(ge=0)
    shared_annotations: int = Field(ge=0)
    discussion_message_count: int = Field(ge=0)
    resolved_discussions: int = Field(ge=0)
    outputs: int = Field(ge=0)
    active_collaborators: int = Field(ge=0)


class ProjectReadingTrendPointResponse(BaseModel):
    date: date
    my_active_ms: int = Field(ge=0)
    team_active_ms: int | None = Field(default=None, ge=0)
    shared_activity_count: int = Field(ge=0)


class ProjectPaperInsightResponse(BaseModel):
    document_id: UUID
    title: str | None
    my_active_ms: int = Field(ge=0)
    my_coverage_percent: float | None = Field(default=None, ge=0, le=100)
    shared_annotation_count: int = Field(ge=0)
    discussion_message_count: int = Field(ge=0)
    last_activity_at: datetime | None


class ProjectInsightsResponse(BaseModel):
    project_id: UUID
    metric_definition_version: str = ACTIVE_READING_DEFINITION_VERSION
    reading_data_since: datetime | None
    activity_history_complete_since: datetime | None
    time_zone: str
    range: ReadingInsightsRange
    mine: ProjectMineInsightsResponse
    team: ProjectTeamInsightsResponse
    trend: list[ProjectReadingTrendPointResponse]
    papers: list[ProjectPaperInsightResponse]
    papers_total_count: int = Field(ge=0)


class ReadingPaperSummaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_ids: list[UUID] = Field(min_length=1, max_length=100)

    @field_validator("document_ids")
    @classmethod
    def require_unique_document_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("document_ids must be unique")
        return value


class ReadingPageBucketResponse(BaseModel):
    start_page: int = Field(ge=1)
    end_page: int = Field(ge=1)
    active_ms: int = Field(ge=0)


class ReadingPaperSummaryItemResponse(BaseModel):
    document_id: UUID
    active_ms: int = Field(ge=0)
    visible_ms: int = Field(ge=0)
    coverage_percent: float | None = Field(default=None, ge=0, le=100)
    page_buckets: list[ReadingPageBucketResponse]


class ReadingPaperSummariesResponse(BaseModel):
    items: list[ReadingPaperSummaryItemResponse]


class ProjectActivityItemResponse(BaseModel):
    id: str
    kind: ProjectActivityKind
    occurred_at: datetime
    actor_display_name: str | None = None
    document_id: UUID | None = None
    document_title: str | None = None


class ProjectActivityResponse(BaseModel):
    project_id: UUID
    items: list[ProjectActivityItemResponse]
    next_cursor: str | None = None


class ResearchProjectBreakdownResponse(BaseModel):
    project_id: UUID
    title: str
    active_ms: int = Field(ge=0)
    session_count: int = Field(ge=0)


class ResearchPaperBreakdownResponse(BaseModel):
    document_id: UUID
    title: str | None
    active_ms: int = Field(ge=0)
    session_count: int = Field(ge=0)
    last_read_at: datetime | None


class ResearchInsightsResponse(BaseModel):
    metric_definition_version: str = ACTIVE_READING_DEFINITION_VERSION
    reading_data_since: datetime | None
    activity_history_complete_since: datetime | None
    time_zone: str
    range: ReadingInsightsRange
    summary: ReadingSummaryResponse
    trend: list[ReadingTrendPointResponse]
    projects: list[ResearchProjectBreakdownResponse]
    top_papers: list[ResearchPaperBreakdownResponse]
    papers_with_activity: int = Field(ge=0)
    annotation_count: int = Field(ge=0)
    conversation_count: int = Field(ge=0)
    output_count: int = Field(ge=0)


class ReadingActivityExportRecordResponse(BaseModel):
    record_type: str = Field(min_length=1, max_length=64)
    payload: dict[str, JsonValue]


class ReadingActivityExportResponse(BaseModel):
    exported_at: datetime
    records: list[ReadingActivityExportRecordResponse]
    next_cursor: str | None = None
