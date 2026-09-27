"""Embedding identity and dimensions, independent of model execution libraries."""

from scholens_ai.model_artifacts import model_artifact

EMBEDDING_DIMENSION = 384
EMBEDDING_MODEL_ID = "intfloat/multilingual-e5-small"
EMBEDDING_MODEL_REVISION = model_artifact().revision
EMBEDDING_MAX_TOKENS = 512
