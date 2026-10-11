import type { Person } from "../organizations/types";

/** A notification as the server words it. `url` is a path inside this app. */
export interface AppNotification {
  id: string;
  type: string;
  title: string;
  body: string;
  url: string;
  actor: Person | null;
  is_read: boolean;
  created_at: string;
}

export interface NotificationPreference {
  category: string;
  title: string;
  description: string;
  in_app: boolean;
  email: boolean;
}
