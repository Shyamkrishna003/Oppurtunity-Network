# PRD — Opportunity Network

**Version:** 1.0  
**Status:** Draft / MVP Planning  
**Stack:** React + TypeScript + Django + DRF + PostgreSQL + Redis + Celery + Django Channels  
**AI:** Not required; MVP is deliberately non-AI

## 1. Executive Summary
Opportunity Network is a professional opportunity platform where people, organizations, and communities publish, discover, distribute, and act on jobs, events, referrals, projects, mentorships, freelance gigs, competitions, co-founder searches, volunteering, scholarships, and learning opportunities.

The primary product abstraction is an **Opportunity**, not a social post.

Core lifecycle:

```text
Create -> Publish -> Distribute -> Discover -> Engage -> Act -> Track Outcome
```

## 2. Problem
Opportunities are fragmented across job boards, WhatsApp/Telegram groups, Discord, social networks, event platforms, alumni groups, and community sites.

Individuals struggle to discover trustworthy opportunities, find referrals, and track applications/events.

Organizations struggle to reach relevant communities and measure application/referral outcomes.

Communities struggle to centralize, moderate, distribute, and measure opportunities.

## 3. Vision
Build trusted infrastructure for professional opportunity distribution:

> One platform where people discover opportunities, communities distribute them, organizations manage them, and outcomes can be tracked from publication to completion.

## 4. Positioning
Do not position this as another LinkedIn.

Position it as:

> **An opportunity network for jobs, events, referrals, projects, and professional communities.**

## 5. Target Users

### Individual Professional
Developers, designers, students, freelancers, job seekers, entrepreneurs, mentors.

Goals: discover, apply, register, request referrals, join projects, find mentors.

### Recruiter / Hiring Manager
Goals: publish jobs, reach communities, manage candidates, track pipeline and hiring outcomes.

### Organization
Startups, companies, NGOs, colleges, training providers, event organizers.

Goals: publish opportunities/events, manage members, applications, and reputation.

### Community Administrator
Developer communities, alumni groups, colleges, professional associations, startup/local chapters.

Goals: manage members, moderate opportunities, promote useful opportunities, organize events, track participation.

### Platform Administrator
Goals: moderation, verification, users/orgs/communities, reports, analytics, audits.

## 6. Core Concept
Every opportunity has:

```text
Creator
Organization (optional)
Type
Title
Description
Audience
Requirements
Location
Deadline
Status
Communities
Interactions
Participants
Outcome
```

Opportunity types for MVP:
1. Job
2. Event
3. Referral
4. Project
5. Mentorship

Post-MVP:
- Freelance gig
- Hackathon
- Competition
- Co-founder
- Volunteer
- Scholarship
- Learning opportunity

## 7. Core User Journeys

### Discover
```text
Login -> Feed -> Filter/Search -> Opportunity -> Save/Share/Apply/Register/Request Referral
```

### Publish Job
```text
Organization -> Create Job -> Requirements -> Select Communities -> Draft -> Publish -> Applications -> Pipeline -> Hire
```

### Referral
```text
Discover Job -> Request Referral -> Select Connection -> Send -> Accept/Decline -> Refer -> Apply -> Track Outcome
```

### Event
```text
Organizer -> Create -> Date/Time/Location/Capacity -> Select Communities -> Publish -> Register -> Waitlist -> QR Check-in -> Complete
```

### Community Distribution
One opportunity can be distributed to multiple communities. Communities may require moderation before publication.

## 8. MVP Requirements

### Authentication
- Registration/login/logout
- Email verification
- Password reset
- Profile
- Basic preferences

### Profile
- Name
- Photo
- Bio
- Skills
- Experience
- Education
- Location
- Remote preference
- Interests
- Communities
- Organization memberships
- Privacy settings

Privacy levels:
`Public | Connections only | Community members | Private`

### Opportunity Feed
Support:
- Global opportunities
- Community opportunities
- Followed organizations
- Saved opportunities
- Deterministically ranked relevant opportunities

Filters:
- Type
- Skill
- Location
- Remote/hybrid/on-site
- Experience
- Community
- Organization
- Date/deadline

Sorting:
- Newest
- Deadline
- Most relevant
- Popular

Deterministic relevance can use explicit weights such as:
```text
+5 matching skill
+3 matching interest
+3 matching community
+2 matching location
+2 matching work mode
+1 followed organization
```

### Opportunity Details
Show title, type, creator, organization, description, requirements, skills, location, work mode, deadline, communities, created date, status, and action.

Actions:
- Job: Apply / Save / Share / Request Referral
- Event: Register / Save / Share
- Project: Join / Save / Share
- Mentorship: Request
- Referral: Request

## 9. Jobs
Fields:
- Title
- Description
- Department
- Employment type
- Experience level
- Skills
- Salary range optional
- Location
- Work mode
- Deadline
- Application method

Application states:
```text
APPLIED
SCREENING
SHORTLISTED
INTERVIEW
OFFER
HIRED
REJECTED
WITHDRAWN
```

Recruiters can move applications through the pipeline.

## 10. Events
Fields:
- Name
- Description
- Organizer
- Start/end date/time
- Venue or online URL
- Capacity
- Registration deadline
- Communities
- Image

Features:
- Registration
- Cancellation
- Waitlist
- Attendee management
- QR check-in
- Attendance tracking
- Reminders

Lifecycle:
```text
DRAFT -> PUBLISHED -> REGISTRATION_OPEN -> REGISTRATION_CLOSED -> COMPLETED/CANCELLED
```

## 11. Referrals
Core differentiator.

A referral request contains:
- Opportunity
- Requester
- Target referrer
- Message
- Status
- Created timestamp
- Response timestamp

Lifecycle:
```text
REQUESTED
ACCEPTED / DECLINED
REFERRED
APPLICATION_SUBMITTED
INTERVIEW
OFFER
JOINED
CLOSED
```

Rules:
- Never silently create a referral.
- Do not expose a user's entire connection graph.
- Respect privacy settings.
- Only eligible users may be selected.

## 12. Projects
Project opportunities help people find collaborators for open source, startups, college projects, hackathons, and side projects.

Fields:
- Title
- Description
- Skills needed
- Team size
- Members
- Deadline
- Repository link
- Status

Future workspace:
- Members
- Tasks
- Discussions
- Files
- Milestones

## 13. Mentorship
Workflow:
```text
Mentor opportunity -> Mentee request -> Accept -> Schedule -> Session -> Feedback
```
MVP may use simple scheduling information rather than a full calendar engine.

## 14. Communities
A community contains:
- Name
- Description
- Logo/cover
- Category
- Rules
- Members
- Admins
- Opportunities
- Events
- Discussions/resources

Admins can approve members, moderate/feature opportunities, create events, manage rules, and view analytics.

## 15. Organizations
Organization page:
- Name
- Logo
- Description
- Website
- Industry
- Location
- Verification status
- Members
- Active/past opportunities

Roles:
`OWNER | ADMIN | RECRUITER | MEMBER`

## 16. Connections
Connection states:
`REQUESTED | ACCEPTED | DECLINED | BLOCKED`

Connections primarily support referrals, direct messaging, and sharing.

## 17. Messaging
MVP:
- One-to-one messaging
- Conversation list
- Read/unread
- Real-time delivery
- Notifications

Use Django Channels for delivery and PostgreSQL for persistence.

## 18. Notifications
Types:
- Referral request/response
- Application status
- Event registration/reminder
- Community invitation
- Followed-community opportunity
- New message
- Organization invitation

Channels:
`In-app | WebSocket | Email`

Users need notification preferences.

## 19. Search
Search:
- Opportunity title
- Description
- Skills
- Organization
- Community
- Location

Examples:
`Django developer`, `React internship`, `startup event`, `Python mentorship`, `Kochi hackathon`.

Use PostgreSQL full-text/trigram search initially.

## 20. Moderation
Reports can target users, organizations, communities, and opportunities.

Categories:
- Spam
- Fraud
- Misleading opportunity
- Harassment
- Inappropriate content
- Fake organization
- Other

States:
`OPEN | UNDER_REVIEW | ACTION_TAKEN | DISMISSED`

Admin actions:
- Hide/remove
- Warn
- Suspend
- Restrict posting
- Verify

All moderation actions are auditable.

## 21. Trust & Verification
Verification types:
- Email verified
- Organization verified
- Community verified
- Organizer verified

Future: domain verification, manual verification, reputation, successful outcomes.

## 22. Admin Dashboard
Users:
- total/active/suspended/new

Organizations:
- total/pending/verified

Communities:
- total/pending/active

Opportunities:
- total/active/expired/reported

Applications:
- total/by status/conversion

Referrals:
- requests/accepted/completed/conversion

Events:
- registrations/attendance/capacity

## 23. Analytics
Opportunity:
`Views -> Saves -> Shares -> Applications/Registrations -> Referrals -> Outcome`

Job funnel:
`Views -> Applications -> Shortlisted -> Interviews -> Offers -> Hired`

Event funnel:
`Views -> Registrations -> Attendance`

Referral funnel:
`Requests -> Accepted -> Referred -> Applications -> Interviews -> Offers -> Joined`

## 24. Monetization — Future
Individual:
- Free browsing/applying/saving/referrals
- Premium advanced filters, analytics, visibility, alerts

Organization:
- Free limited opportunities
- Paid advanced applicant management, analytics, featured opportunities, branding

Community:
- Free basic community
- Paid analytics, moderation, featured opportunities, branding

## 25. Non-Functional Requirements
Performance targets:
- API p95 < 500ms for normal CRUD/search requests where practical
- Paginated feeds
- No unbounded list endpoints
- Near-real-time WebSocket delivery

Design for graceful failure: email outages should queue/retry; disconnected sockets should reconnect; slow work must not block HTTP requests.

## 26. Security
Must include:
- Authentication
- Authorization
- Object-level permissions
- Rate limiting
- CSRF/CORS protections where applicable
- Input/file validation
- Secure password/token handling
- Security headers
- Audit logs
- Abuse reporting

Never leak sensitive data through APIs, WebSockets, logs, or analytics.

## 27. Initial Data Model
```text
User
 ├── Connections
 ├── Applications
 ├── ReferralRequests
 ├── EventRegistrations
 ├── Memberships
 ├── Messages
 └── Notifications

Organization
 ├── Members
 └── Opportunities

Community
 ├── Members
 ├── Opportunities
 └── Events

Opportunity
 ├── Creator
 ├── Organization
 ├── Communities
 ├── Applications
 ├── ReferralRequests
 └── Analytics
```

Suggested tables:
```text
users
user_profiles
organizations
organization_members
communities
community_members
community_rules
opportunities
opportunity_communities
opportunity_skills
jobs
applications
events
event_registrations
event_checkins
projects
project_members
mentorships
mentorship_requests
connections
conversations
conversation_members
messages
notifications
notification_preferences
reports
moderation_actions
subscriptions
audit_logs
```

## 28. API Surface
Illustrative endpoints:
```text
/auth/register
/auth/login
/auth/logout
/auth/refresh
/auth/password-reset

/users/me
/users/{id}

/organizations
/organizations/{id}
/organizations/{id}/members
/organizations/{id}/opportunities

/communities
/communities/{id}
/communities/{id}/join
/communities/{id}/leave
/communities/{id}/members

/opportunities
/opportunities/{id}
/opportunities/{id}/publish
/opportunities/{id}/close
/opportunities/{id}/save

/jobs/{id}/apply
/applications
/applications/{id}
/applications/{id}/status

/referrals
/referrals/requests
/referrals/requests/{id}/accept
/referrals/requests/{id}/decline

/events/{id}/register
/events/{id}/cancel-registration
/events/{id}/check-in

/connections
/connections/{id}/accept
/connections/{id}/decline

/conversations
/conversations/{id}/messages

/notifications
/notifications/{id}/read

/reports
```

## 29. WebSocket
Suggested routes:
```text
/ws/notifications/
/ws/conversations/{conversation_id}/
```

Events:
```text
notification.created
notification.read
message.created
application.updated
referral.updated
event.updated
```

Only send information the connected user is authorized to see.

## 30. Background Jobs
Celery jobs:
```text
send_email
send_event_reminder
expire_opportunity
send_opportunity_digest
send_application_notification
send_referral_notification
aggregate_analytics
cleanup_expired_data
```

Jobs must be retry-safe and idempotent.

## 31. Development Phases

### Phase 1 — Foundation
Docker, PostgreSQL, Redis, Django, React, auth, profiles, permissions.

### Phase 2 — Opportunities
Opportunity model, create/publish/close, feed, search, filters, save/share.

### Phase 3 — Jobs
Job specialization, applications, recruiter dashboard, state machine.

### Phase 4 — Communities
Community creation, membership, feed, distribution, moderation.

### Phase 5 — Referrals
Connections, referral requests, acceptance, lifecycle, notifications.

### Phase 6 — Events
Creation, registration, capacity, waitlist, QR check-in, reminders.

### Phase 7 — Real-Time
WebSocket notifications, messaging, read states.

### Phase 8 — Trust/Admin
Reports, moderation, verification, audit logs, admin dashboard.

### Phase 9 — Analytics
Opportunity, job, event, and referral funnels.

### Phase 10 — Production Hardening
Security review, load testing, query optimization, monitoring, CI/CD, backups, documentation.

## 32. MVP Success Criteria

Individual:
1. Register/login.
2. Build profile.
3. Discover/search/filter.
4. Save.
5. Apply to jobs.
6. Track applications.
7. Connect.
8. Request/accept referrals.
9. Join communities.
10. Register/check in to events.
11. Receive notifications.
12. Message users.
13. Report content.

Organization:
1. Create organization.
2. Invite members.
3. Publish opportunities.
4. Manage applications.
5. Publish events.
6. View basic analytics.

Community admin:
1. Manage members.
2. Moderate opportunities.
3. Publish events.
4. Feature opportunities.
5. Review reports.

Platform admin:
1. Manage users.
2. Manage organizations.
3. Manage communities.
4. Moderate.
5. View analytics.
6. Audit administrative actions.

## 33. Why This Is Technically Impressive
The project should demonstrate:
- Domain/state-machine modeling
- Multi-tenancy
- RBAC/object-level permissions
- PostgreSQL data modeling and indexing
- Redis caching/rate limiting
- Celery asynchronous jobs
- WebSocket real-time features
- Search
- Transactions/idempotency
- File storage
- Moderation and audit logs
- Security
- Analytics
- Docker/CI/CD/observability

The architecture should remain justified by actual business requirements.

## 34. Deliberate Non-Goals
Do not attempt to become:
- A complete LinkedIn replacement
- A full enterprise HRMS
- A full enterprise ATS
- A full ticketing platform
- A social-media clone
- A project-management replacement
- An AI recommendation platform

## 35. Differentiation
1. Opportunity-first architecture.
2. One opportunity can be distributed across trusted communities.
3. Referrals are an explicit tracked workflow.
4. Outcomes are tracked, not only engagement.
5. Organizations and communities can be verified and moderated.
6. Deterministic discovery works without AI.

## 36. Example End-to-End Scenario
Example Labs publishes a remote React/TypeScript developer role.

```text
Organization verified
 -> Recruiter creates job
 -> Selects React India + Kochi Developers
 -> Job published
 -> Candidate discovers it through skill/community match
 -> Candidate requests referral from connection
 -> Connection accepts
 -> Referral submitted
 -> Candidate applies
 -> Screening
 -> Interview
 -> Offer
 -> Hired
```

Analytics:
```text
Views: 1,200
Applications: 84
Referrals: 17
Interviews: 12
Offers: 3
Hired: 2
```

This illustrates the core loop:

`Opportunity -> Distribution -> Discovery -> Referral -> Application -> Outcome`

## 37. North Star Metric
**Successful Opportunity Outcomes**

Examples:
- Hires
- Event attendances
- Project joins
- Completed mentorships
- Successful referrals

Secondary metrics:
- Active users
- Active opportunities
- Application conversion
- Registration conversion
- Referral conversion
- Community engagement
- Organization retention

## 38. Final Product Definition
Opportunity Network is a multi-tenant SaaS platform connecting:

```text
People
   ↕
Communities
   ↕
Organizations
   ↕
Opportunities
```

through:

```text
Jobs
Events
Referrals
Projects
Mentorship
```

with infrastructure for:

```text
Discovery
Distribution
Applications
Registration
Messaging
Notifications
Moderation
Analytics
Trust
```

The defining loop is:

```text
CREATE
  ↓
DISTRIBUTE
  ↓
DISCOVER
  ↓
ENGAGE
  ↓
ACT
  ↓
TRACK OUTCOME
```
