"""Identity commands independent of HTTP and persistence."""

from pydantic import BaseModel, ConfigDict, PrivateAttr


class SetUserBlockedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blocked: bool


class SetUserBlockedResponse(BaseModel):
    success: bool
    message: str
    _changed: bool = PrivateAttr(default=False)

    @property
    def changed(self) -> bool:
        """Internal mutation result; intentionally absent from the HTTP DTO."""
        return self._changed


class SetUserAdminResponse(BaseModel):
    success: bool
    changed: bool
    message: str
