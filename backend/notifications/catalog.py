"""What each notification type means: its preference category, whether it can be emailed,
and how it reads.

Notifications are worded when they are shown, from the small ``payload`` saved with them, so
the wording can be improved later without rewriting stored rows.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from notifications.models import Category, Notification, NotificationType

T = NotificationType
Payload = dict[str, Any]


@dataclass(frozen=True)
class Rendered:
    title: str
    body: str
    # Path in the web app that the notification opens.
    url: str


@dataclass(frozen=True)
class Spec:
    category: Category
    # False for types that already have their own dedicated email (invitations), so the
    # person is not emailed twice about one thing.
    emailable: bool
    render: Callable[[Notification], Rendered]


# Per category: (in the app, by email). Used when a person has not chosen otherwise.
# Email is off by default for review queues, which can be frequent for a busy moderator.
DEFAULTS: dict[Category, tuple[bool, bool]] = {
    Category.INVITATIONS: (True, True),
    Category.MEMBERSHIP: (True, True),
    Category.REVIEW: (True, False),
    Category.POSTINGS: (True, True),
    Category.APPLICATIONS: (True, True),
    Category.CONNECTIONS: (True, True),
    Category.REFERRALS: (True, True),
}

DESCRIPTIONS: dict[Category, str] = {
    Category.INVITATIONS: "When you are invited to an organization or a community.",
    Category.MEMBERSHIP: "Decisions about your requests to join, role changes, and removals.",
    Category.REVIEW: (
        "Requests to join, shared opportunities and job applications waiting for your decision."
    ),
    Category.POSTINGS: "What communities decide about your opportunities, and when one expires.",
    Category.APPLICATIONS: "When a job you applied to moves your application on, or decides.",
    Category.CONNECTIONS: "When someone asks to connect with you, or accepts your request.",
    Category.REFERRALS: (
        "When a connection asks you to refer them, answers your request, or a referral moves on."
    ),
}


def _community(payload: Payload) -> str:
    return f"/communities/{payload['community_id']}"


def _opportunity(payload: Payload) -> str:
    return f"/opportunities/{payload['opportunity_id']}"


def _application(payload: Payload) -> str:
    return f"/applications/{payload['application_id']}"


def _organization_invitation(notification: Notification) -> Rendered:
    # The link's secret is derived, never stored: see organizations.tokens. Imported here so
    # that this app, which every other app calls into, depends on none of them at load time.
    from organizations.tokens import invitation_token

    p = notification.payload
    return Rendered(
        title=f"You are invited to join {p['organization_name']}",
        body=f"{p['inviter_name']} invited you as {p['role_label']}. Open to accept or decline.",
        url=f"/organization-invitations/{invitation_token(notification.target_id)}",
    )


def _simple(
    title: str, body: str, url: Callable[[Payload], str]
) -> Callable[[Notification], Rendered]:
    """A renderer whose title and body are templates over the payload."""

    def render(notification: Notification) -> Rendered:
        p = notification.payload
        return Rendered(title=title.format(**p), body=body.format(**p), url=url(p))

    return render


def _share_rejected(notification: Notification) -> Rendered:
    p = notification.payload
    reason = f" Reason given: {p['reason']}" if p.get("reason") else ""
    return Rendered(
        title=f"{p['community_name']} declined “{p['opportunity_title']}”",
        body=f"It will not be shown there.{reason} You can change it and offer it again.",
        url=_opportunity(p),
    )


def _referral(payload: Payload) -> str:
    return f"/referrals/{payload['referral_id']}"


def _referral_outcome(notification: Notification) -> Rendered:
    p = notification.payload
    if p["status"] == "JOINED":
        title = f"{p['requester_name']} got the job: “{p['opportunity_title']}”"
        body = "The person you referred was hired. Thank you for vouching for them."
    else:
        title = f"{p['requester_name']} applied to “{p['opportunity_title']}”"
        body = "Their application now carries your referral."
    return Rendered(title=title, body=body, url=_referral(p))


def _application_advanced(notification: Notification) -> Rendered:
    p = notification.payload
    if p["status"] == "HIRED":
        title = f"You were selected for “{p['opportunity_title']}”"
        body = "Congratulations. The employer marked your application as hired."
    else:
        title = f"Your application to “{p['opportunity_title']}” moved to {p['status_label']}"
        body = "Open your application to see where it stands."
    return Rendered(title=title, body=body, url=_application(p))


SPECS: dict[NotificationType, Spec] = {
    T.ORGANIZATION_INVITATION: Spec(Category.INVITATIONS, False, _organization_invitation),
    T.ORGANIZATION_ROLE_CHANGED: Spec(
        Category.MEMBERSHIP,
        True,
        _simple(
            "Your role in {organization_name} changed",
            "You are now {role_label} there.",
            lambda p: f"/organizations/{p['organization_id']}",
        ),
    ),
    T.ORGANIZATION_REMOVED: Spec(
        Category.MEMBERSHIP,
        True,
        _simple(
            "You were removed from {organization_name}",
            "You no longer have access to what its members can see.",
            lambda p: "/organizations",
        ),
    ),
    T.COMMUNITY_INVITATION: Spec(
        Category.INVITATIONS,
        False,
        _simple(
            "You are invited to join {community_name}",
            "{inviter_name} invited you. Open the community to accept or decline.",
            _community,
        ),
    ),
    T.COMMUNITY_JOIN_REQUESTED: Spec(
        Category.REVIEW,
        True,
        _simple(
            "{person_name} asked to join {community_name}",
            "Open the community to approve or decline the request.",
            _community,
        ),
    ),
    T.COMMUNITY_JOIN_APPROVED: Spec(
        Category.MEMBERSHIP,
        True,
        _simple(
            "You are now a member of {community_name}",
            "Your request to join was approved.",
            _community,
        ),
    ),
    T.COMMUNITY_JOIN_REJECTED: Spec(
        Category.MEMBERSHIP,
        True,
        _simple(
            "Your request to join {community_name} was declined",
            "You can ask again later, or look for other communities.",
            lambda p: "/communities",
        ),
    ),
    T.COMMUNITY_REMOVED: Spec(
        Category.MEMBERSHIP,
        True,
        _simple(
            "You were removed from {community_name}",
            "You are no longer a member of this community.",
            lambda p: "/communities",
        ),
    ),
    T.SHARE_SUBMITTED: Spec(
        Category.REVIEW,
        True,
        _simple(
            "“{opportunity_title}” is waiting for review in {community_name}",
            "{person_name} shared it. Open the community to approve or decline.",
            _community,
        ),
    ),
    T.SHARE_APPROVED: Spec(
        Category.POSTINGS,
        True,
        _simple(
            "{community_name} approved “{opportunity_title}”",
            "It is now shown to the community's members.",
            _opportunity,
        ),
    ),
    T.SHARE_REJECTED: Spec(Category.POSTINGS, True, _share_rejected),
    T.SHARE_REMOVED: Spec(
        Category.POSTINGS,
        True,
        _simple(
            "{community_name} removed “{opportunity_title}”",
            "It is no longer shown there and cannot be shared with that community again.",
            _opportunity,
        ),
    ),
    T.OPPORTUNITY_EXPIRED: Spec(
        Category.POSTINGS,
        True,
        _simple(
            "“{opportunity_title}” has expired",
            "Its deadline passed, so it no longer takes applications. You can archive it.",
            _opportunity,
        ),
    ),
    T.APPLICATION_RECEIVED: Spec(
        Category.REVIEW,
        True,
        _simple(
            "{person_name} applied to “{opportunity_title}”",
            "Open the application to read it and see the resume.",
            _application,
        ),
    ),
    T.APPLICATION_WITHDRAWN: Spec(
        Category.REVIEW,
        True,
        _simple(
            "{person_name} withdrew from “{opportunity_title}”",
            "They are no longer a candidate for this job.",
            _application,
        ),
    ),
    T.APPLICATION_ADVANCED: Spec(Category.APPLICATIONS, True, _application_advanced),
    T.APPLICATION_REJECTED: Spec(
        Category.APPLICATIONS,
        True,
        _simple(
            "Your application to “{opportunity_title}” was not selected",
            "The employer has decided not to take it further. Thank you for applying.",
            _application,
        ),
    ),
    T.CONNECTION_REQUESTED: Spec(
        Category.CONNECTIONS,
        True,
        _simple(
            "{person_name} wants to connect",
            "Open your connections to accept or decline.",
            lambda p: "/connections?show=requests",
        ),
    ),
    T.CONNECTION_ACCEPTED: Spec(
        Category.CONNECTIONS,
        True,
        _simple(
            "{person_name} accepted your request to connect",
            "You are now connected.",
            lambda p: "/connections",
        ),
    ),
    T.REFERRAL_REQUESTED: Spec(
        Category.REFERRALS,
        True,
        _simple(
            "{requester_name} asked you for a referral",
            "It is for “{opportunity_title}”. Open the request to accept or decline.",
            _referral,
        ),
    ),
    T.REFERRAL_ACCEPTED: Spec(
        Category.REFERRALS,
        True,
        _simple(
            "{referrer_name} agreed to refer you",
            "It is for “{opportunity_title}”. You will be told when the referral is made.",
            _referral,
        ),
    ),
    T.REFERRAL_DECLINED: Spec(
        Category.REFERRALS,
        True,
        _simple(
            "{referrer_name} declined your referral request",
            "It was for “{opportunity_title}”. You can still apply, or ask someone else.",
            _referral,
        ),
    ),
    T.REFERRAL_EXPIRED: Spec(
        Category.REFERRALS,
        True,
        _simple(
            "Your referral request to {referrer_name} expired",
            "It was for “{opportunity_title}” and was not answered in time.",
            _referral,
        ),
    ),
    T.REFERRAL_REFERRED: Spec(
        Category.REFERRALS,
        True,
        _simple(
            "{referrer_name} referred you for “{opportunity_title}”",
            "The people hiring can see it. If you have not applied yet, apply now.",
            _referral,
        ),
    ),
    T.REFERRAL_OUTCOME: Spec(Category.REFERRALS, True, _referral_outcome),
    T.REFERRAL_CLOSED: Spec(
        Category.REFERRALS,
        True,
        _simple(
            "The referral for “{opportunity_title}” was closed",
            "Between {requester_name} and {referrer_name}. Nothing more will happen with it.",
            _referral,
        ),
    ),
}


def render(notification: Notification) -> Rendered:
    return SPECS[NotificationType(notification.type)].render(notification)
