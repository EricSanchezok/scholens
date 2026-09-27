"""Stable test-only configuration for Jobs service imports."""

import os

# Unit tests must never discover workstation or instance-role credentials.
os.environ["AWS_ACCESS_KEY_ID"] = "scholens-unit-test"
os.environ["AWS_SECRET_ACCESS_KEY"] = "scholens-unit-test"
os.environ["AWS_EC2_METADATA_DISABLED"] = "true"
os.environ.pop("AWS_SESSION_TOKEN", None)

os.environ.setdefault("S3_BUCKET_NAME", "scholens-test")
os.environ.setdefault("SCHOLENS_AI_DEEPSEEK_API_KEY", "test-provider-key")
