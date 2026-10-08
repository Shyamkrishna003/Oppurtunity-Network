import { useState } from "react";
import { useForm } from "react-hook-form";

import { CheckboxField, SelectField } from "../../components/Field";
import { Notice } from "../../components/Notice";
import { errorMessage } from "../../services/formErrors";
import type { OwnProfile } from "../auth/types";
import { useUpdateProfile } from "./api";
import { VISIBILITIES } from "./labels";

type Values = Pick<
  OwnProfile,
  "visibility" | "show_contact" | "show_history" | "accepts_referral_requests"
>;

export function PrivacyForm({ profile }: { profile: OwnProfile }) {
  const update = useUpdateProfile();
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    formState: { isDirty },
  } = useForm<Values>({ defaultValues: profile });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      const me = await update.mutateAsync(values);
      reset(me.profile);
    } catch (error) {
      setFormError(errorMessage(error));
    }
  });

  return (
    <form onSubmit={(event) => void onSubmit(event)} noValidate>
      {formError && <Notice kind="error">{formError}</Notice>}
      {update.isSuccess && !isDirty && <Notice kind="ok">Saved.</Notice>}
      <SelectField
        label="Who can open my profile"
        hint="Connections and communities arrive in a later release; until then those two options show your profile only to you."
        {...register("visibility")}
      >
        {Object.entries(VISIBILITIES).map(([value, label]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </SelectField>
      <CheckboxField label="Show my email address on my profile" {...register("show_contact")} />
      <CheckboxField label="Show my experience and education" {...register("show_history")} />
      <CheckboxField
        label="Let my connections ask me for referrals"
        {...register("accepts_referral_requests")}
      />
      <button type="submit" className="primary" disabled={update.isPending || !isDirty}>
        {update.isPending ? "Saving…" : "Save"}
      </button>
    </form>
  );
}
