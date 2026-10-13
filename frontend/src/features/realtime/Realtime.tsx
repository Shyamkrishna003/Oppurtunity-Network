import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { useAppDispatch } from "../../app/store";
import { applicationKeys } from "../applications/api";
import { eventKeys } from "../events/api";
import { useSessionStatus } from "../auth/api";
import { connectionKeys } from "../connections/api";
import { notificationKeys } from "../notifications/api";
import { referralKeys } from "../referrals/api";
import { streamStatusChanged } from "./realtimeSlice";
import { StreamConnection, type StreamEvent } from "./socket";

function refreshNotifications(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: notificationKeys.unreadCount });
  void queryClient.invalidateQueries({ queryKey: notificationKeys.lists });
}

/**
 * An event says that something changed, not what the page should now show: the affected
 * queries are refetched through the API, which applies the usual permission checks.
 */
function apply(queryClient: QueryClient, event: StreamEvent): void {
  switch (event.type) {
    case "notification.created":
    case "notification.read":
      refreshNotifications(queryClient);
      break;
    case "application.updated":
      // One of the viewer's applications moved: its page, "my applications", and the job
      // page that shows its status.
      void queryClient.invalidateQueries({ queryKey: applicationKeys.all });
      void queryClient.invalidateQueries({ queryKey: ["opportunities"] });
      break;
    case "registration.updated":
      // The viewer got a place from the waitlist, or lost their registration: the event's
      // page (how they stand, the joining link) and "my events".
      void queryClient.invalidateQueries({ queryKey: eventKeys.all });
      void queryClient.invalidateQueries({ queryKey: ["opportunities"] });
      break;
    case "connection.updated":
      // Someone asked the viewer, accepted them, took a request back or left: the lists,
      // and any open profile, whose connect button depends on it.
      void queryClient.invalidateQueries({ queryKey: connectionKeys.all });
      void queryClient.invalidateQueries({ queryKey: ["users"] });
      break;
    case "referral.updated":
      // A referral the viewer is part of moved: its page, the lists, and the job page that
      // shows the viewer's requests.
      void queryClient.invalidateQueries({ queryKey: referralKeys.all });
      break;
    default:
      // An event type from a newer server; ignoring it is always safe.
      break;
  }
}

/** Keeps the live connection open while someone is signed in. Renders nothing. */
export function Realtime() {
  const session = useSessionStatus();
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();

  useEffect(() => {
    if (session !== "authenticated") {
      return;
    }
    const connection = new StreamConnection({
      onStatus: (status) => {
        dispatch(streamStatusChanged(status));
        if (status === "live") {
          // Whatever happened while we were not connected was never pushed.
          refreshNotifications(queryClient);
        }
      },
      onEvent: (event) => {
        apply(queryClient, event);
      },
    });
    connection.start();
    return () => {
      connection.stop();
    };
  }, [session, dispatch, queryClient]);

  return null;
}
