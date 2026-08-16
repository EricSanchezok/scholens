"""Shared Scholens email-provider process settings."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class ScholensEmailSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    scholens_aliyun_dm_access_key_id: str = ""
    scholens_aliyun_dm_access_key_secret: str = ""
    scholens_aliyun_dm_account_name: str = ""
    scholens_aliyun_dm_from_alias: str = "Scholens"
    scholens_aliyun_dm_reply_to_address: bool = True

    @property
    def configured(self) -> bool:
        return all(self._credential_values)

    @property
    def _credential_values(self) -> tuple[str, str, str]:
        return (
            self.scholens_aliyun_dm_access_key_id,
            self.scholens_aliyun_dm_access_key_secret,
            self.scholens_aliyun_dm_account_name,
        )

    def validate_configuration(self, *, required: bool) -> None:
        configured_count = sum(bool(value) for value in self._credential_values)
        if configured_count not in {0, len(self._credential_values)}:
            raise RuntimeError(
                "SCHOLENS_ALIYUN_DM_ACCESS_KEY_ID, "
                "SCHOLENS_ALIYUN_DM_ACCESS_KEY_SECRET, and "
                "SCHOLENS_ALIYUN_DM_ACCOUNT_NAME must be configured together"
            )
        if required and not self.configured:
            raise RuntimeError(
                "Aliyun DirectMail credentials are required in production"
            )


email_settings = ScholensEmailSettings()

__all__ = ["ScholensEmailSettings", "email_settings"]
