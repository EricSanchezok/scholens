from __future__ import annotations

from unittest.mock import AsyncMock, patch

from src.schemas import DataTableCellValue, DataTableResult, DataTableRow
from src.tasks import construct_data_table_task


def test_process_data_table_executes_real_task_path_and_reports_progress() -> None:
    request = {
        "research_item_id": "research-1",
        "title": "Evidence table",
        "table": {
            "columns": ["Finding"],
            "papers": [
                {
                    "id": "paper-1",
                    "title": "Paper One",
                    "raw_content": "Evidence body",
                }
            ],
        },
    }
    processed = DataTableResult(
        success=True,
        columns=["Finding"],
        rows=[
            DataTableRow(
                document_id="paper-1",
                values={"Finding": DataTableCellValue(value="Supported", citations=[])},
            )
        ],
        row_failures=[],
    )
    progress: list[str] = []

    async def construct(*, data_table_schema, status_callback):
        assert data_table_schema.papers[0].id == "paper-1"
        status_callback("extract for Paper One completed")
        return processed

    with (
        patch("src.tasks._claim_job", return_value=True) as claim,
        patch("src.tasks.construct_data_table", new=AsyncMock(side_effect=construct)),
        patch("src.tasks._deliver_webhook", return_value=True) as deliver,
        patch(
            "src.tasks._log_data_table_progress",
            side_effect=lambda _task_id, status: progress.append(status),
        ),
    ):
        result = construct_data_table_task.apply(
            args=(request, "https://server.example/webhook", None),
            task_id="data-table-job-1",
            throw=True,
        ).get()

    claim.assert_called_once_with(None, task_id="data-table-job-1")
    assert progress == [
        "Starting data table construction",
        "extract for Paper One completed",
        "Data table construction complete!",
    ]
    assert result["status"] == "completed"
    assert result["result"]["research_item_id"] == "research-1"
    deliver.assert_called_once()
