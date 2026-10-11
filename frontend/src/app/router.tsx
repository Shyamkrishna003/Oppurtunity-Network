import { createBrowserRouter, type RouteObject } from "react-router";

import { AnonymousOnly, RequireAuth } from "../features/auth/guards";
import { AppLayout } from "../layouts/AppLayout";
import { PublicLayout } from "../layouts/PublicLayout";
import { CommunitiesPage } from "../routes/CommunitiesPage";
import { CommunityCreatePage } from "../routes/CommunityCreatePage";
import { CommunityPage } from "../routes/CommunityPage";
import { ForgotPasswordPage } from "../routes/ForgotPasswordPage";
import { HomePage } from "../routes/HomePage";
import { LoginPage } from "../routes/LoginPage";
import { NotFoundPage } from "../routes/NotFoundPage";
import { OrganizationCreatePage } from "../routes/OrganizationCreatePage";
import { OrganizationInvitationPage } from "../routes/OrganizationInvitationPage";
import { OrganizationPage } from "../routes/OrganizationPage";
import { OrganizationsPage } from "../routes/OrganizationsPage";
import { ProfilePage } from "../routes/ProfilePage";
import { RegisterPage } from "../routes/RegisterPage";
import { ResetPasswordPage } from "../routes/ResetPasswordPage";
import { RouteError } from "../routes/RouteError";
import { SettingsAccountPage } from "../routes/SettingsAccountPage";
import { SettingsProfilePage } from "../routes/SettingsProfilePage";
import { VerifyEmailPage } from "../routes/VerifyEmailPage";

export const routes: RouteObject[] = [
  {
    errorElement: <RouteError />,
    children: [
      {
        element: <AppLayout />,
        children: [
          { index: true, element: <HomePage /> },
          // Organizations and public communities can be browsed without an account.
          { path: "organizations", element: <OrganizationsPage /> },
          { path: "communities", element: <CommunitiesPage /> },
          {
            element: <RequireAuth />,
            children: [
              // Before the ":id" routes, which would otherwise capture "new".
              { path: "organizations/new", element: <OrganizationCreatePage /> },
              { path: "communities/new", element: <CommunityCreatePage /> },
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
