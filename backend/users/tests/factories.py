from django.utils import timezone
from factory.declarations import LazyFunction, Sequence, Trait
from factory.django import DjangoModelFactory

from users.models import User


class UserFactory(DjangoModelFactory[User]):
    class Meta:
        model = User

    class Params:
        unverified = Trait(email_verified_at=None)

    email = Sequence(lambda n: f"user{n}@example.com")
    password = "correct-horse-battery"
    email_verified_at = LazyFunction(timezone.now)

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        # Through the manager, so the password is hashed and the profile exists.
        return model_class.objects.create_user(*args, **kwargs)
