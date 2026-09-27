from app.bootstrap.document_rollout import in_document_rollout


def test_document_rollout_cohorts_are_stable_and_nested():
    users = range(1, 1001)
    cohorts = {
        percentage: {u for u in users if in_document_rollout(u, percentage)}
        for percentage in (0, 10, 50, 100)
    }
    assert cohorts[0] == set()
    assert 60 < len(cohorts[10]) < 140
    assert cohorts[10] < cohorts[50] < cohorts[100]
    assert cohorts[100] == set(users)
    assert cohorts[10] == {u for u in users if in_document_rollout(u, 10)}


def test_document_rollout_settings_reject_an_invalid_percentage():
    import pytest
    from pydantic import ValidationError
    from app.bootstrap.settings import AppSettings

    for percentage in (-1, 101):
        with pytest.raises(ValidationError):
            AppSettings(document_pipeline_percent=percentage)
