import importlib

from app.helpers import email as email_helper


CURRENT_SOURCE_REPOSITORY = "https://github.com/EricSanchezok/scholens"


def test_email_source_repository_defaults_to_current_project(monkeypatch) -> None:
    monkeypatch.delenv("SOURCE_REPOSITORY_URL", raising=False)
    reloaded = importlib.reload(email_helper)

    assert reloaded.SOURCE_REPOSITORY_URL == CURRENT_SOURCE_REPOSITORY
    welcome = reloaded.load_email_template("subscription_welcome.html")
    assert f"{CURRENT_SOURCE_REPOSITORY}/issues" in welcome


def test_email_source_repository_remains_configurable(monkeypatch) -> None:
    configured = "https://code.example/scholens"
    monkeypatch.setenv("SOURCE_REPOSITORY_URL", configured)
    reloaded = importlib.reload(email_helper)

    assert reloaded.SOURCE_REPOSITORY_URL == configured
    assert f"{configured}/issues" in reloaded.load_email_template(
        "subscription_welcome.html"
    )


def test_email_templates_use_text_branding_without_legacy_routes(monkeypatch) -> None:
    monkeypatch.delenv("SOURCE_REPOSITORY_URL", raising=False)
    reloaded = importlib.reload(email_helper)

    for template_name in (
        "data_table_complete.html",
        "profile.html",
        "project_invite.html",
        "subscription_welcome.html",
    ):
        rendered = reloaded.load_email_template(template_name)
        assert "Scholens" in rendered
        assert "{{brand_logo_url}}" not in rendered
        assert "<img" not in rendered
        assert "/blog/" not in rendered
