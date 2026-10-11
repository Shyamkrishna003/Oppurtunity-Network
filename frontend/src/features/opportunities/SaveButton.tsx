import { useSessionStatus } from "../auth/api";
import { useSetSaved } from "./api";

/** Save or unsave an opportunity. Renders nothing for visitors, who have nowhere to save to. */
export function SaveButton({ id, title, saved }: { id: string; title: string; saved: boolean }) {
  const status = useSessionStatus();
  const setSaved = useSetSaved();
  if (status !== "authenticated") {
    return null;
  }
  // While the request is in flight, show the state being asked for.
  const shown = setSaved.isPending ? (setSaved.variables?.saved ?? saved) : saved;
  return (
    <button
      type="button"
      aria-pressed={shown}
      disabled={setSaved.isPending}
      onClick={() => setSaved.mutate({ id, saved: !saved })}
    >
      {shown ? "Saved" : "Save"} <span className="visually-hidden">{title}</span>
    </button>
  );
}
