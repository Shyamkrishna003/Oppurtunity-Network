from django.test import Client


def test_openapi_schema_is_served():
    response = Client().get("/api/v1/schema/")

    assert response.status_code == 200
    assert b"Opportunity Network API" in response.content
