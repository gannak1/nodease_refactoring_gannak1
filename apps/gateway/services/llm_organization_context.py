from uuid import UUID

from fastapi import HTTPException


def resolve_llm_organization_id(
    x_organization_id: UUID | None,
    body_organization_id: UUID | None = None,
) -> UUID:
    # Resolves explicit LLM organization scope without default-org mutation MBA-43
    if (
        x_organization_id is not None
        and body_organization_id is not None
        and x_organization_id != body_organization_id
    ):
        raise HTTPException(status_code=400, detail="organization_id_mismatch")

    resolved_organization_id = x_organization_id or body_organization_id
    if resolved_organization_id is None:
        raise HTTPException(status_code=400, detail="organization_id_required")
    return resolved_organization_id
