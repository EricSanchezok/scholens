"""Transactional email provider adapters."""

from app.modules.notifications.infrastructure.aliyun import (
    AliyunTransactionalEmailSender,
)

__all__ = ["AliyunTransactionalEmailSender"]
