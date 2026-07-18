from apps.gateway.main import app


def test_external_action_credential_routes_and_safe_response_schema_are_registered():
    schema = app.openapi()
    paths = schema["paths"]
    prefix = "/api/v1/external-action-credentials/credentials"

    assert {"get", "post"} <= set(paths[prefix])
    assert {"get", "patch"} <= set(paths[f"{prefix}/{{credential_id}}"])
    assert {"post"} <= set(paths[f"{prefix}/{{credential_id}}/revoke"])
    assert {"get"} <= set(paths[f"{prefix}/{{credential_id}}/permissions"])
    assert {"put", "delete"} <= set(
        paths[f"{prefix}/{{credential_id}}/permissions/users/{{user_id}}"]
    )
    assert {"put", "delete"} <= set(
        paths[f"{prefix}/{{credential_id}}/permissions/teams/{{team_id}}"]
    )

    properties = schema["components"]["schemas"][
        "ExternalActionCredentialResponse"
    ]["properties"]
    assert {
        "secret",
        "encrypted_secret",
        "encryption_key_version",
        "encryption_algorithm",
    }.isdisjoint(properties)

    option_properties = schema["components"]["schemas"][
        "ExternalActionCredentialOptionResponse"
    ]["properties"]
    assert set(option_properties) == {
        "id",
        "credential_name",
        "provider",
        "revision",
        "status",
    }

    access_parameters = paths[
        "/api/v1/organizations/{organization_id}/members/{user_id}/resource-access"
    ]["get"]["parameters"]
    resource_type = next(
        parameter
        for parameter in access_parameters
        if parameter["name"] == "resourceType"
    )
    assert "external_action_credential" in resource_type["schema"]["enum"]
