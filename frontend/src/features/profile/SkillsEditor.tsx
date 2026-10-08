import { useState } from "react";

import { Notice } from "../../components/Notice";
import { errorMessage } from "../../services/formErrors";
import type { Me, SkillSets } from "../auth/types";
import { useSaveSkills } from "./api";
import { SkillPicker } from "./SkillPicker";

const sameIds = (a: SkillSets, b: SkillSets) =>
  (["has", "interested"] as const).every(
    (kind) =>
      a[kind].length === b[kind].length &&
      a[kind].every((skill, index) => skill.id === b[kind][index]?.id),
  );

export function SkillsEditor({ me }: { me: Me }) {
  const [draft, setDraft] = useState<SkillSets>(me.skills);
  const save = useSaveSkills();
  const dirty = !sameIds(draft, me.skills);

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate(draft, { onSuccess: setDraft });
      }}
    >
      {save.isError && <Notice kind="error">{errorMessage(save.error)}</Notice>}
      {save.isSuccess && !dirty && <Notice kind="ok">Saved.</Notice>}
      <SkillPicker
        label="Skills I have"
        value={draft.has}
        onChange={(has) => setDraft({ ...draft, has })}
        canCreate={me.email_verified}
      />
      <SkillPicker
        label="Skills I want to learn or work with"
        value={draft.interested}
        onChange={(interested) => setDraft({ ...draft, interested })}
        canCreate={me.email_verified}
      />
      <button type="submit" className="primary" disabled={save.isPending || !dirty}>
        {save.isPending ? "Saving…" : "Save skills"}
      </button>
    </form>
  );
}
