import { createBrowserRouter } from "react-router";

import { AppLayout } from "../layouts/AppLayout";
import { PublicLayout } from "../layouts/PublicLayout";
import { HomePage } from "../routes/HomePage";
import { LoginPage } from "../routes/LoginPage";
import { NotFoundPage } from "../routes/NotFoundPage";
import { RouteError } from "../routes/RouteError";

export const router = createBrowserRouter([
  {
    errorElement: <RouteError />,
    children: [
      {
        element: <AppLayout />,
        children: [
          { index: true, element: <HomePage /> },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
      {
        element: <PublicLayout />,
        children: [{ path: "login", element: <LoginPage /> }],
      },
    ],
  },
]);
