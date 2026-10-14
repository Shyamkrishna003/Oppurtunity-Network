"""Reports sent to a community's own moderators, and what those moderators can do."""

import pytest
from django.db import IntegrityError, transaction

from audit.models import AuditLog
from communities.tests.factories import CommunityMemberFactory, community_with_roles
from moderation.models import Report
from notifications.models import Notification
from opportunities.models import OpportunityCommunity
from opportunities.tests.factories import distribute, make_job
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

REPORTS = "/api/v1/reports/"
PLATFORM = "/api/v1/moderation/reports/"


def told(user) -> list[str]:
    return list(
        Notification.objects.filter(recipient=user)
        .order_by("created_at")
        .values_list("type", flat=True)
    )


def queue(community, report=None, action="") -> str:
    base = f"/api/v1/communities/{community.pk}/reports/"
    return base if report is None else f"{base}{report.pk}/{action}"


@pytest.fixture
def shown():
    """A community with every role, a member who is nobody special, and a job it shows."""
    community, members = community_with_roles("ADMIN", "MODERATOR", "MEMBER")
    poster = CommunityMemberFactory.create(community=community).user
    job = make_job(status="PUBLISHED", creator=poster, title="Easy money")
    share = distribute(job, community, submitted_by=poster)
    return community, members, job, share


def file(api_as, reporter, job, community, **overrides):
    return api_as(reporter).post(
        REPORTS,
        {
            "target_type": "OPPORTUNITY",
            "target_id": str(job.pk),
            "category": "SCAM",
            "description": "Asks for a fee.",
            "community_id": str(community.pk),
            **overrides,
        },
    )


def filed(job, community, reporter=None, **fields) -> Report:
    return Report.objects.create(
        reporter=reporter or CommunityMemberFactory.create(community=community).user,
        target_type="OPPORTUNITY",
        target_opportunity=job,
        category="SCAM",
        scope_community=community,
        **fields,
    )


# --- Sending a report to a community ----------------------------------------------------


def test_a_member_reports_to_the_community_and_its_moderators_are_told_once(api_as, shown):
    community, members, job, _ = shown
    reporter = members["MEMBER"].user

    response = file(api_as, reporter, job, community)

    assert response.status_code == 201
    report = Report.objects.get()
    assert report.scope_community == community
    for role in ("OWNER", "ADMIN", "MODERATOR"):
        assert told(members[role].user) == ["COMMUNITY_REPORT_FILED"]
    notice = Notification.objects.filter(recipient=members["OWNER"].user).get()
    # Nothing in it says who reported.
    assert notice.actor is None
    assert str(reporter.pk) not in str(notice.payload)
    assert notice.payload["opportunity_title"] == "Easy money"

    # A second complaint about the same thing is not more news.
    other = CommunityMemberFactory.create(community=community).user
    assert file(api_as, other, job, community).status_code == 201
    assert told(members["OWNER"].user) == ["COMMUNITY_REPORT_FILED"]


def test_a_moderator_who_reports_is_not_told_about_their_own_report(api_as, shown):
    community, members, job, _ = shown

    assert file(api_as, members["MODERATOR"].user, job, community).status_code == 201

    assert told(members["MODERATOR"].user) == []
    assert told(members["OWNER"].user) == ["COMMUNITY_REPORT_FILED"]


def test_a_community_report_is_not_filed_under_the_community_in_the_audit_trail(api_as, shown):
    community, members, job, _ = shown

    file(api_as, members["MEMBER"].user, job, community)

    # Its owners read that trail, and the actor on this record is the reporter.
    assert AuditLog.objects.get(action="report.filed").community_id is None


def test_who_cannot_report_to_a_community(api_as, shown):
    community, members, job, share = shown
    outsider = UserFactory.create()

    refused = file(api_as, outsider, job, community)
    assert (refused.status_code, refused.json()["code"]) == (422, "not_a_member")

    private, _ = community_with_roles(visibility="PRIVATE")
    assert file(api_as, outsider, job, private).status_code == 404

    elsewhere, others = community_with_roles("MEMBER")
    refused = file(api_as, others["MEMBER"].user, job, elsewhere)
    assert (refused.status_code, refused.json()["code"]) == (422, "not_in_community")

    OpportunityCommunity.objects.filter(pk=share.pk).update(status="PENDING")
    refused = file(api_as, members["MEMBER"].user, job, community)
    assert (refused.status_code, refused.json()["code"]) == (422, "not_in_community")
    assert Report.objects.count() == 0


def test_only_an_opportunity_can_be_reported_to_a_community(api_as, shown):
    community, members, _, _ = shown
    someone = members["ADMIN"].user

    response = api_as(members["MEMBER"].user).post(
        REPORTS,
        {
            "target_type": "USER",
            "target_id": str(someone.pk),
            "category": "HARASSMENT",
            "community_id": str(community.pk),
        },
    )

    assert (response.status_code, response.json()["code"]) == (422, "community_scope_unavailable")
    with pytest.raises(IntegrityError), transaction.atomic():
        Report.objects.create(
            reporter=members["MEMBER"].user,
            target_type="USER",
            target_user=someone,
            category="SPAM",
            scope_community=community,
        )


# --- Reading the community's queue ------------------------------------------------------


def test_the_community_queue_is_for_its_moderators_and_never_names_the_reporter(api, api_as, shown):
    community, members, job, _ = shown
    reporter = members["MEMBER"].user
    report = filed(job, community, reporter=reporter, description="Asks for a fee.")

    assert api.get(queue(community)).status_code == 401
    assert api_as(reporter).get(queue(community)).status_code == 403
    assert api_as(UserFactory.create()).get(queue(community)).status_code == 403
    # Running the platform gives nothing here.
    staff = UserFactory.create(platform_role="ADMIN")
    assert api_as(staff).get(queue(community)).status_code == 403
    assert api_as(staff).get(queue(community, report)).status_code == 403

    for role in ("OWNER", "ADMIN", "MODERATOR"):
        listed = api_as(members[role].user).get(queue(community))
        assert listed.status_code == 200
        (row,) = listed.json()["results"]
        assert row["id"] == str(report.pk)
        assert row["description"] == "Asks for a fee."
        assert "reporter" not in row

    detail = api_as(members["MODERATOR"].user).get(queue(community, report)).json()
    assert "reporter" not in detail
    assert str(reporter.pk) not in str(detail)
    assert detail["in_progress_on_target"] == 1
    assert detail["shown_in_community"] is True
    assert detail["can_decide"] is True


def test_a_private_community_hides_its_queue_from_outsiders(api_as):
    community, _ = community_with_roles(visibility="PRIVATE")

    assert api_as(UserFactory.create()).get(queue(community)).status_code == 404


def test_the_two_queues_never_mix(api_as, shown):
    community, members, job, _ = shown
    theirs = filed(job, community)
    platforms = Report.objects.create(
        reporter=UserFactory.create(), target_type="OPPORTUNITY", target_opportunity=job,
        category="SPAM",
    )  # fmt: skip
    staff = UserFactory.create(platform_role="MODERATOR")
    moderator = members["MODERATOR"].user

    listed = api_as(staff).get(PLATFORM).json()["results"]
    assert [row["id"] for row in listed] == [str(platforms.pk)]
    assert api_as(staff).get(f"{PLATFORM}{theirs.pk}/").status_code == 404
    assert api_as(staff).post(f"{PLATFORM}{theirs.pk}/claim/").status_code == 404
    resolve = {"action": "HIDE", "reason": "Scam."}
    assert api_as(staff).post(f"{PLATFORM}{theirs.pk}/resolve/", resolve).status_code == 404

    listed = api_as(moderator).get(queue(community)).json()["results"]
    assert [row["id"] for row in listed] == [str(theirs.pk)]
    assert api_as(moderator).get(queue(community, platforms)).status_code == 404
    assert api_as(moderator).post(queue(community, platforms, "claim/")).status_code == 404
    # The count a community sees is of its own reports only.
    assert api_as(moderator).get(queue(community, theirs)).json()["in_progress_on_target"] == 1

    # Nor does one community's moderator reach into another's.
    other, others = community_with_roles("MODERATOR")
    assert api_as(others["MODERATOR"].user).get(queue(other, theirs)).status_code == 404
    assert api_as(others["MODERATOR"].user).get(queue(community, theirs)).status_code == 403


# --- Deciding ---------------------------------------------------------------------------


def test_a_community_moderator_takes_and_dismisses_a_report(api_as, shown):
    community, members, job, share = shown
    moderator = members["MODERATOR"].user
    report = filed(job, community)

    claimed = api_as(moderator).post(queue(community, report, "claim/"))
    assert claimed.status_code == 200
    assert claimed.json()["status"] == "UNDER_REVIEW"
    assert claimed.json()["assigned_to"]["id"] == str(moderator.pk)

    dismissed = api_as(moderator).post(queue(community, report, "dismiss/"), {"note": "Fine."})
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "DISMISSED"
    assert dismissed.json()["resolution_note"] == "Fine."
    assert dismissed.json()["can_decide"] is False

    share.refresh_from_db()
    assert share.status == "APPROVED"
    assert told(report.reporter) == ["REPORT_REVIEWED"]
    # Both steps are in the community's own trail.
    trail = AuditLog.objects.filter(community_id=community.pk).order_by("created_at")
    assert [log.action for log in trail] == ["report.claimed", "report.resolved"]


def test_a_plain_member_cannot_decide(api_as, shown):
    community, members, job, _ = shown
    report = filed(job, community)
    member = members["MEMBER"].user

    for action, data in (("claim/", {}), ("dismiss/", {}), ("remove/", {"reason": "x"})):
        assert api_as(member).post(queue(community, report, action), data).status_code == 403
    assert api_as(member).post(queue(community, report, "escalate/")).status_code == 403
    report.refresh_from_db()
    assert report.status == "OPEN"


def test_removing_takes_it_out_of_this_community_only(api_as, shown):
    community, members, job, share = shown
    elsewhere, _ = community_with_roles()
    other_share = distribute(job, elsewhere)
    first, second = filed(job, community), filed(job, community)
    in_other = filed(job, elsewhere)
    platforms = Report.objects.create(
        reporter=UserFactory.create(), target_type="OPPORTUNITY", target_opportunity=job,
        category="SPAM",
    )  # fmt: skip

    response = api_as(members["ADMIN"].user).post(
        queue(community, first, "remove/"), {"reason": "Asks members for a fee."}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ACTION_TAKEN"
    assert data["shown_in_community"] is False
    assert data["in_progress_on_target"] == 0
    share.refresh_from_db()
    assert (share.status, share.reviewed_by) == ("REMOVED", members["ADMIN"].user)
    # Nothing else moved: the other community, the opportunity itself, other queues.
    other_share.refresh_from_db()
    job.refresh_from_db()
    assert other_share.status == "APPROVED"
    assert job.moderation_status == "VISIBLE"
    for untouched in (in_other, platforms):
        untouched.refresh_from_db()
        assert untouched.status == "OPEN"
    # Everyone who complained here is answered, in the same words.
    for settled in (first, second):
        settled.refresh_from_db()
        assert settled.status == "ACTION_TAKEN"
        assert settled.resolution_note == "Asks members for a fee."
        assert told(settled.reporter) == ["REPORT_REVIEWED"]
    assert "SHARE_REMOVED" in told(job.creator)
    actions = set(
        AuditLog.objects.filter(community_id=community.pk).values_list("action", flat=True)
    )
    assert actions == {"opportunity.share_reviewed", "report.resolved"}


def test_removing_needs_a_reason_and_something_still_shown(api_as, shown):
    community, members, job, share = shown
    report = filed(job, community)
    moderator = api_as(members["MODERATOR"].user)

    assert moderator.post(queue(community, report, "remove/"), {"reason": "  "}).status_code == 400

    OpportunityCommunity.objects.filter(pk=share.pk).update(status="REMOVED")
    response = moderator.post(queue(community, report, "remove/"), {"reason": "Scam."})
    assert (response.status_code, response.json()["code"]) == (409, "action_not_possible")
    report.refresh_from_db()
    assert report.status == "OPEN"  # still to be dismissed or passed on

    moderator.post(queue(community, report, "dismiss/"), {"note": "Already gone."})
    again = moderator.post(queue(community, report, "remove/"), {"reason": "Scam."})
    assert again.status_code == 409


def test_nobody_decides_a_report_about_what_they_posted_or_one_they_made(api_as, shown):
    community, members, job, share = shown
    owner = members["OWNER"].user
    mine = make_job(status="PUBLISHED", creator=owner)
    distribute(mine, community)
    about_mine = filed(mine, community)
    by_me = filed(job, community, reporter=owner)

    for report in (about_mine, by_me):
        assert api_as(owner).get(queue(community, report)).json()["can_decide"] is False
        for action, data in (("claim/", {}), ("dismiss/", {}), ("remove/", {"reason": "x"})):
            assert api_as(owner).post(queue(community, report, action), data).status_code == 403
        assert api_as(owner).post(queue(community, report, "escalate/")).status_code == 403
        report.refresh_from_db()
        assert report.status == "OPEN"
    # Someone else in the community can.
    other = api_as(members["ADMIN"].user)
    assert other.post(queue(community, about_mine, "claim/")).status_code == 200


def test_passing_a_report_up_to_the_platform(api_as, shown):
    community, members, job, share = shown
    moderator = members["MODERATOR"].user
    report = filed(job, community)
    api_as(moderator).post(queue(community, report, "claim/"))

    response = api_as(moderator).post(queue(community, report, "escalate/"))

    assert response.status_code == 204
    report.refresh_from_db()
    assert (report.scope_community, report.status, report.assigned_to) == (None, "OPEN", None)
    assert api_as(moderator).get(queue(community, report)).status_code == 404
    assert api_as(moderator).get(queue(community)).json()["results"] == []
    log = AuditLog.objects.get(action="report.escalated")
    assert (log.community_id, log.actor) == (community.pk, moderator)
    # A second attempt finds nothing there.
    assert api_as(moderator).post(queue(community, report, "escalate/")).status_code == 404

    # It is now the platform's, and they can do what a community cannot.
    staff = api_as(UserFactory.create(platform_role="MODERATOR"))
    assert [row["id"] for row in staff.get(PLATFORM).json()["results"]] == [str(report.pk)]
    resolved = staff.post(f"{PLATFORM}{report.pk}/resolve/", {"action": "HIDE", "reason": "Scam."})
    assert resolved.status_code == 200
    job.refresh_from_db()
    assert job.moderation_status == "HIDDEN"
    assert told(report.reporter) == ["REPORT_REVIEWED"]


def test_a_decided_report_cannot_be_passed_up(api_as, shown):
    community, members, job, _ = shown
    report = filed(job, community, status="DISMISSED")

    response = api_as(members["OWNER"].user).post(queue(community, report, "escalate/"))

    assert (response.status_code, response.json()["code"]) == (409, "already_resolved")
    report.refresh_from_db()
    assert report.scope_community == community


def test_a_platform_action_also_settles_what_communities_were_asked(api_as, shown):
    community, _, job, _ = shown
    theirs = filed(job, community)
    staff = api_as(UserFactory.create(platform_role="MODERATOR"))

    response = staff.post(
        "/api/v1/moderation/actions/",
        {"target_type": "OPPORTUNITY", "target_id": str(job.pk), "action": "HIDE", "reason": "x"},
    )

    assert response.status_code == 201
    theirs.refresh_from_db()
    assert theirs.status == "ACTION_TAKEN"
    assert told(theirs.reporter) == ["REPORT_REVIEWED"]
