import type { RouteObject } from "react-router";
import { AppLayout } from "./AppLayout";
import { InboxPage, MetricsPage, NotFoundPage } from "./pages";

export const routes: RouteObject[] = [
  {
    element: <AppLayout />,
    children: [
      { path: "/", element: <InboxPage /> },
      { path: "/metrics", element: <MetricsPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];
