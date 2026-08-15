"""PDF ingestion and parsing domain."""

from src.pdf.mineru import MinerUConfig
from src.pdf.state import parser_state_redis_url


def validate_pdf_runtime_configuration() -> None:
    """Fail fast for non-secret parser runtime requirements."""
    MinerUConfig.from_runtime(token="runtime-validation-placeholder")
    parser_state_redis_url()
