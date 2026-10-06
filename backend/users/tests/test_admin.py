import pytest
from django.test import Client

from users.models import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_browser():
    admin = User.objects.create_superuser("root@example.com", "correct-horse-battery")
    client = Client()
    client.force_login(admin)
    return client


def test_user_admin_pages_render(admin_browser):
    user = User.objects.get()

    assert admin_browser.get("/admin/users/user/").status_code == 200
    assert admin_browser.get("/admin/users/user/add/").status_code == 200
    assert admin_browser.get(f"/admin/users/user/{user.pk}/change/").status_code == 200


def test_user_can_be_created_from_admin(admin_browser):
    response = admin_browser.post(
        "/admin/users/user/add/",
        {
            "email": "New.Person@Example.com",
            "password1": "correct-horse-battery",
            "password2": "correct-horse-battery",
        },
    )

    assert response.status_code == 302
    assert User.objects.filter(email="new.person@example.com").exists()
