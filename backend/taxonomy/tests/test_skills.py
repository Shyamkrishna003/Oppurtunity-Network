import pytest

from common.throttles import ScopedThrottle
from taxonomy.models import Skill, skill_slug
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

URL = "/api/v1/skills/"


def names(response):
    return [s["name"] for s in response.json()]


def test_slugs_keep_symbols_that_distinguish_skills():
    slugs = {name: skill_slug(name) for name in ("C", "C++", "C#", ".NET", "Node.js", "CI/CD")}

    assert slugs == {
        "C": "c",
        "C++": "c-plus-plus",
        "C#": "c-sharp",
        ".NET": "dot-net",
        "Node.js": "node-dot-js",
        "CI/CD": "ci-cd",
    }


def test_seeded_skills_are_available():
    assert Skill.objects.count() > 50
    assert Skill.objects.filter(name="C++").exists()


def test_suggestions_require_authentication(api):
    assert api.get(URL).status_code == 401


def test_suggestions_put_prefix_matches_first_and_are_bounded(api_as):
    client = api_as(UserFactory())

    java = names(client.get(URL, {"q": "java"}))
    script = names(client.get(URL, {"q": "script"}))
    everything = client.get(URL)

    assert java[:2] == ["Java", "JavaScript"]
    assert set(script) >= {"JavaScript", "TypeScript"}
    assert len(everything.json()) == 20
    assert names(everything) == sorted(names(everything), key=str.casefold)


def test_suggestions_tolerate_typos(api_as):
    client = api_as(UserFactory())

    assert "Python" in names(client.get(URL, {"q": "pyhton"}))
    assert names(client.get(URL, {"q": "zzzzqqq"})) == []


def test_suggestions_treat_wildcards_literally(api_as):
    assert names(api_as(UserFactory()).get(URL, {"q": "%"})) == []


def test_verified_users_can_add_skills(api_as):
    user = UserFactory()
    client = api_as(user)

    created = client.post(URL, {"name": "  Apache   Airflow "})
    again = client.post(URL, {"name": "apache airflow"})
    existing = client.post(URL, {"name": "PYTHON"})

    assert created.status_code == 201
    assert created.json()["name"] == "Apache Airflow"
    assert created.json()["slug"] == "apache-airflow"
    assert (again.status_code, again.json()["id"]) == (200, created.json()["id"])
    assert (existing.status_code, existing.json()["name"]) == (200, "Python")
    assert Skill.objects.get(slug="apache-airflow").created_by == user


def test_unverified_users_cannot_add_skills(api_as):
    client = api_as(UserFactory(unverified=True))

    response = client.post(URL, {"name": "Apache Airflow"})

    assert (response.status_code, response.json()["code"]) == (403, "email_not_verified")
    assert client.get(URL).status_code == 200


@pytest.mark.parametrize("name", ["", "   ", "<script>", "+++", "x" * 61, "emoji 🚀"])
def test_skill_names_are_validated(api_as, name):
    response = api_as(UserFactory()).post(URL, {"name": name})

    assert response.status_code == 400


def test_adding_skills_is_rate_limited_but_searching_is_not(api_as, monkeypatch):
    monkeypatch.setitem(ScopedThrottle.THROTTLE_RATES, "skill_create", "1/day")
    client = api_as(UserFactory())

    assert client.post(URL, {"name": "Skill One"}).status_code == 201
    assert client.post(URL, {"name": "Skill Two"}).status_code == 429
    assert client.get(URL).status_code == 200
