from apps.gateway.main import app


def test_mail_credential_routes_and_safe_response_schema_are_registered():
    schema = app.openapi()
    paths = schema["paths"]

    assert {"get", "post"} <= set(paths["/api/v1/mail/credentials"])
    assert {"get", "patch", "delete"} <= set(
        paths["/api/v1/mail/credentials/{credential_id}"]
    )
    assert {"get"} <= set(paths["/api/v1/mail/credentials/{credential_id}/permissions"])
    assert {"put", "delete"} <= set(
        paths["/api/v1/mail/credentials/{credential_id}/permissions/users/{user_id}"]
    )
    assert {"put", "delete"} <= set(
        paths["/api/v1/mail/credentials/{credential_id}/permissions/teams/{team_id}"]
    )

    properties = schema["components"]["schemas"]["MailCredentialResponse"]["properties"]
    assert "email_preview" in properties
    assert {
        "email_address",
        "secret",
        "encrypted_secret",
        "encryption_key_version",
    }.isdisjoint(properties)

    access_parameters = paths[
        "/api/v1/organizations/{organization_id}/members/{user_id}/resource-access"
    ]["get"]["parameters"]
    resource_type = next(
        parameter
        for parameter in access_parameters
        if parameter["name"] == "resourceType"
    )
    assert "mail_credential" in resource_type["schema"]["enum"]

    option_properties = schema["components"]["schemas"]["MailCredentialOptionResponse"][
        "properties"
    ]
    assert set(option_properties) == {
        "id",
        "credential_name",
        "provider",
        "email_preview",
        "status",
    }

    update_properties = schema["components"]["schemas"]["MailCredentialUpdate"][
        "properties"
    ]
    assert set(update_properties) == {"credential_name", "secret"}
