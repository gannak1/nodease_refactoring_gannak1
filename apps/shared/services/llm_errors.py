class LLMRuntimeAccessError(Exception):
    """Base runtime access error for LLM credential routing."""

    status_code = 500
    detail = "llm_runtime_access_failed"

    def __init__(self, detail: str | None = None):
        super().__init__(detail or self.detail)
        self.detail = detail or self.detail


class LLMCredentialNotAvailableError(LLMRuntimeAccessError):
    """No usable credential exists for the requested organization/model."""

    status_code = 404
    detail = "llm_credential_not_available"


class LLMCredentialPermissionDeniedError(LLMRuntimeAccessError):
    """A credential exists, but the user cannot use it."""

    status_code = 403
    detail = "llm_credential_permission_denied"


class LLMModelPolicyDeniedError(LLMRuntimeAccessError):
    """The requested model is blocked by team or membership policy."""

    status_code = 403
    detail = "llm_model_policy_denied"
