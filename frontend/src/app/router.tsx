import { createBrowserRouter, type RouteObject } from "react-router";

import { AnonymousOnly, RequireAuth } from "../features/auth/guards";
import { AppLayout } from "../layouts/AppLayout";
import { PublicLayout } from "../layouts/PublicLayout";
import { ForgotPasswordPage } from "../routes/ForgotPasswordPage";
import { HomePage } from "../routes/HomePage";
import { LoginPage } from "../routes/LoginPage";
import { NotFoundPage } from "../routes/NotFoundPage";
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
          {
            element: <RequireAuth />,
            children: [
              { path: "users/:userId", element: <ProfilePage /> },
              { path: "settings/profile", element: <SettingsProfilePage /> },
              { path: "settings/account", element: <SettingsAccountPage /> },
            ],
          },
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
