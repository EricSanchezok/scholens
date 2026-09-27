"""Stable, non-secret configuration for Server test imports."""

import os

# Unit tests must never discover workstation or instance-role credentials.
os.environ["AWS_ACCESS_KEY_ID"] = "scholens-unit-test"
os.environ["AWS_SECRET_ACCESS_KEY"] = "scholens-unit-test"
os.environ["AWS_EC2_METADATA_DISABLED"] = "true"
os.environ.pop("AWS_SESSION_TOKEN", None)

os.environ.setdefault("SCHOLENS_AI_DEEPSEEK_API_KEY", "test-provider-key")
os.environ.setdefault("STRIPE_API_KEY", "sk_test_scholens")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_test_scholens")
os.environ.setdefault("STRIPE_MONTHLY_PRICE_ID", "price_test_monthly")
os.environ.setdefault("STRIPE_YEARLY_PRICE_ID", "price_test_yearly")
