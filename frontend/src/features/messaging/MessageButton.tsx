import { useNavigate } from "react-router";

import { Notice } from "../../components/Notice";
import { errorMessage } from "../../services/formErrors";
import { useStartConversation } from "./api";

/** Opens the conversation with someone (creating it the first time) and goes to it. */
export function MessageButton({ userId, name }: { userId: string; name: string }) {
  const navigate = useNavigate();
  const start = useStartConversation();
  return (
    <>
      <button
        type="button"
        disabled={start.isPending}
        onClick={() =>
          start.mutate(userId, {
            onSuccess: (conversation) => void navigate(`/messages/${conversation.id}`),
          })
        }
      >
        Message <span className="visually-hidden">{name}</span>
      </button>
      {start.isError && <Notice kind="error">{errorMessage(start.error)}</Notice>}
    </>
  );
}
