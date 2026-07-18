from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

ExternalActionCredentialProvider = Literal["github", "slack_api", "slack_webhook"]
ExternalActionCredentialStatus = Literal["active", "revoked"]


def _validate_secret(value: SecretStr) -> SecretStr:
    raw = value.get_secret_value()
    if raw != raw.strip() or any(char in raw for char in "\r\n\x00"):
        raise ValueError("secret contains a forbidden control character or whitespace")
    return value


class ExternalActionCredentialCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential_name: str = Field(min_length=1, max_length=255)
    provider: ExternalActionCredentialProvider
    secret: SecretStr = Field(min_length=1, max_length=4096)

    @field_validator("credential_name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("credential_name must not be blank")
        return stripped

    @field_validator("secret")
    @classmethod
    def validate_secret(cls, value: SecretStr) -> SecretStr:
        return _validate_secret(value)


class ExternalActionCredentialUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    credential_name: str | None = Field(default=None, min_length=1, max_length=255)
    secret: SecretStr | None = Field(default=None, min_length=1, max_length=4096)

    @field_validator("credential_name")
    @classmethod
    def strip_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("credential_name must not be blank")
        return stripped

    @field_validator("secret")
    @classmethod
    def validate_optional_secret(cls, value: SecretStr | None) -> SecretStr | None:
        return _validate_secret(value) if value is not None else None

    @model_validator(mode="after")
    def require_change(self) -> "ExternalActionCredentialUpdate":
        if not ({"credential_name", "secret"} & self.model_fields_set):
            raise ValueError("at least one field must be provided")
        return self


class ExternalActionCredentialRevoke(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)


class ExternalActionCredentialResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    organization_id: UUID
    credential_name: str
    provider: ExternalActionCredentialProvider
    status: ExternalActionCredentialStatus
    revision: int
    created_at: datetime
    updated_at: datetime
    revoked_at: datetime | None = None


class ExternalActionCredentialOptionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    credential_name: str
    provider: ExternalActionCredentialProvider
    revision: int
    status: ExternalActionCredentialStatus


class ExternalActionCredentialPermissionGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auth_state: Literal["viewer", "operator", "builder", "manager"]


class ExternalActionCredentialPermissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    grantee_organization_id: UUID
    auth_state: str
    assigned_by: UUID
    assigned_at: datetime
