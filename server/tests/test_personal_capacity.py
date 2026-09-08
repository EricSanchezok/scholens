from app.modules.billing.domain.entitlements import entitlements_for
from app.shared.domain.enums import SubscriptionPlan


def test_personal_capacity_has_no_model_or_per_project_meter():
    basic = entitlements_for(SubscriptionPlan.BASIC).as_limits()
    researcher = entitlements_for(SubscriptionPlan.RESEARCHER).as_limits()
    assert basic == {
        "paper_uploads": 200,
        "knowledge_base_size_kb": 1024 * 1024,
        "projects": 10,
    }
    assert researcher == {
        "paper_uploads": 2000,
        "knowledge_base_size_kb": 10 * 1024 * 1024,
        "projects": 50,
    }
