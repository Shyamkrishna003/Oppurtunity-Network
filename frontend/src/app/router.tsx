import { createBrowserRouter, Outlet, type RouteObject } from "react-router";

import { AnonymousOnly, RequireAuth } from "../features/auth/guards";
import { Realtime } from "../features/realtime/Realtime";
import { AppLayout } from "../layouts/AppLayout";
import { PublicLayout } from "../layouts/PublicLayout";
import { ApplicationPage } from "../routes/ApplicationPage";
import { ApplicationsPage } from "../routes/ApplicationsPage";
import { CommunitiesPage } from "../routes/CommunitiesPage";
import { CommunityCreatePage } from "../routes/CommunityCreatePage";
import { CommunityPage } from "../routes/CommunityPage";
import { ConnectionsPage } from "../routes/ConnectionsPage";
import { ForgotPasswordPage } from "../routes/ForgotPasswordPage";
import { HomePage } from "../routes/HomePage";
import { LoginPage } from "../routes/LoginPage";
import { MyOpportunitiesPage } from "../routes/MyOpportunitiesPage";
import { NotFoundPage } from "../routes/NotFoundPage";
import { NotificationsPage } from "../routes/NotificationsPage";
import { OpportunitiesPage } from "../routes/OpportunitiesPage";
import { OpportunityCreatePage } from "../routes/OpportunityCreatePage";
import { OpportunityEditPage } from "../routes/OpportunityEditPage";
import { OpportunityPage } from "../routes/OpportunityPage";
import { OrganizationCreatePage } from "../routes/OrganizationCreatePage";
import { OrganizationInvitationPage } from "../routes/OrganizationInvitationPage";
import { OrganizationPage } from "../routes/OrganizationPage";
import { OrganizationsPage } from "../routes/OrganizationsPage";
import { PipelinePage } from "../routes/PipelinePage";
import { ProfilePage } from "../routes/ProfilePage";
import { RegisterPage } from "../routes/RegisterPage";
import { ResetPasswordPage } from "../routes/ResetPasswordPage";
import { RouteError } from "../routes/RouteError";
import { SavedOpportunitiesPage } from "../routes/SavedOpportunitiesPage";
import { SettingsAccountPage } from "../routes/SettingsAccountPage";
import { SettingsNotificationsPage } from "../routes/SettingsNotificationsPage";
import { SettingsProfilePage } from "../routes/SettingsProfilePage";
import { VerifyEmailPage } from "../routes/VerifyEmailPage";

export const routes: RouteObject[] = [
  {
    // Above both layouts, so the live connection survives moving between them.
    element: (
      <>
        <Realtime />
        <Outlet />
      </>
    ),
    errorElement: <RouteError />,
    children: [
      {
        element: <AppLayout />,
        children: [
          { index: true, element: <HomePage /> },
          // Organizations and public communities can be browsed without an account.
          { path: "organizations", element: <OrganizationsPage /> },
          { path: "communities", element: <CommunitiesPage /> },
          { path: "opportunities", element: <OpportunitiesPage /> },
          {
            element: <RequireAuth />,
            children: [
              // Before the ":id" routes, which would otherwise capture "new".
              { path: "organizations/new", element: <OrganizationCreatePage /> },
              { path: "communities/new", element: <CommunityCreatePage /> },
              { path: "opportunities/new", element: <OpportunityCreatePage /> },
              { path: "opportunities/:opportunityId/edit", element: <OpportunityEditPage /> },
              { path: "opportunities/:opportunityId/applications", element: <PipelinePage /> },
              { path: "my/opportunities", element: <MyOpportunitiesPage /> },
              { path: "saved", element: <SavedOpportunitiesPage /> },
              { path: "applications", element: <ApplicationsPage /> },
              { path: "applications/:applicationId", element: <ApplicationPage /> },
              { path: "connections", element: <ConnectionsPage /> },
              { path: "notifications", element: <NotificationsPage /> },
              { path: "settings/notifications", element: <SettingsNotificationsPage /> },
              {
                path: "organization-invitations/:token",
                element: <OrganizationInvitationPage />,
              },
              { path: "users/:userId", element: <ProfilePage /> },
              { path: "settings/profile", element: <SettingsProfilePage /> },
              { path: "settings/account", element: <SettingsAccountPage /> },
            ],
          },
          { path: "organizations/:organizationId", element: <OrganizationPage /> },
          { path: "communities/:communityId", element: <CommunityPage /> },
          // A published public job can be read without an account.
          { path: "opportunities/:opportunityId", element: <OpportunityPage /> },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
      {
        element: <PublicLayout />,
        children: [
          {
            element: <AnonymousOnly />,
            children: [
              { path: "login", element: <LoginPage /> },
              { path: "register", element: <RegisterPage /> },
            ],
          },
          // Reachable signed in or out: the links arrive by email on any device.
          { path: "verify-email", element: <VerifyEmailPage /> },
          { path: "forgot-password", element: <ForgotPasswordPage /> },
          { path: "reset-password", element: <ResetPasswordPage /> },
        ],
      },
    ],
  },
];

export const router = createBrowserRouter(routes);
