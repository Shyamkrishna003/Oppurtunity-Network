from django.apps import AppConfig


class UsersConfig(AppConfig):
    name = "users"

    def ready(self) -> None:
        from users import schema  # noqa: F401  registers the OpenAPI auth scheme
