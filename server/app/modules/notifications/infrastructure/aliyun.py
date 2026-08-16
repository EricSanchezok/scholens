"""Aliyun DirectMail adapter for Scholens product email."""

from __future__ import annotations

from typing import Any

from Tea.exceptions import TeaException

from app.modules.notifications.application import (
    EmailDeliveryError,
    TransactionalEmailMessage,
)


class AliyunTransactionalEmailSender:
    """Send transactional email without provider-owned automatic retries."""

    def __init__(
        self,
        *,
        access_key_id: str,
        access_key_secret: str,
        account_name: str,
        from_alias: str,
        reply_to_address: bool,
        client: Any | None = None,
    ) -> None:
        self._account_name = account_name
        self._from_alias = from_alias
        self._reply_to_address = reply_to_address
        self._client = client or self._build_client(access_key_id, access_key_secret)

    @staticmethod
    def _build_client(access_key_id: str, access_key_secret: str) -> Any:
        from alibabacloud_dm20151123.client import Client as DmClient
        from alibabacloud_tea_openapi import models as open_api_models

        return DmClient(
            open_api_models.Config(
                access_key_id=access_key_id,
                access_key_secret=access_key_secret,
                endpoint="dm.aliyuncs.com",
            )
        )

    async def send(
        self,
        *,
        to_address: str,
        message: TransactionalEmailMessage,
    ) -> None:
        from alibabacloud_dm20151123 import models as dm_models
        from alibabacloud_tea_util import models as util_models

        request = dm_models.SingleSendMailRequest(
            account_name=self._account_name,
            from_alias=self._from_alias,
            address_type=1,
            reply_to_address=self._reply_to_address,
            to_address=to_address,
            subject=message.subject,
            html_body=message.html_body,
            text_body=message.text_body,
            click_trace="0",
        )
        runtime = util_models.RuntimeOptions(
            autoretry=False,
            connect_timeout=5_000,
            read_timeout=30_000,
        )
        try:
            await self._client.single_send_mail_with_options_async(request, runtime)
        except Exception as exc:
            if isinstance(exc, TeaException):
                raw_code = str(getattr(exc, "code", "")).casefold()
                status_code = int(getattr(exc, "statusCode", 0) or 0)
                throttled = "throttl" in raw_code or status_code == 429
                transient = (
                    throttled
                    or status_code == 408
                    or status_code >= 500
                    or any(
                        marker in raw_code
                        for marker in (
                            "timeout",
                            "serviceunavailable",
                            "internalerror",
                        )
                    )
                )
                code = (
                    "provider_throttled"
                    if throttled
                    else "provider_unavailable"
                    if transient
                    else "provider_rejected"
                )
                raise EmailDeliveryError(code, transient=transient) from exc
            raise EmailDeliveryError("provider_unavailable", transient=True) from exc


__all__ = ["AliyunTransactionalEmailSender"]
