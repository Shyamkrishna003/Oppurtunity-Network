from factory.declarations import PostGenerationMethodCall, Sequence
from factory.django import DjangoModelFactory

from users.models import User


class UserFactory(DjangoModelFactory[User]):
    class Meta:
        model = User
        skip_postgeneration_save = True

    email = Sequence(lambda n: f"user{n}@example.com")
    password = PostGenerationMethodCall("set_password", "correct-horse-battery")

    @classmethod
    def _after_postgeneration(cls, instance, create, results=None):
        if create:
            instance.save(update_fields=["password"])
