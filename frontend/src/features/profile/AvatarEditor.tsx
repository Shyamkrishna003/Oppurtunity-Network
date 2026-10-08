import { useRef, useState } from "react";

import { Avatar } from "../../components/Avatar";
import { Notice } from "../../components/Notice";
import { errorMessage } from "../../services/formErrors";
import type { OwnProfile } from "../auth/types";
import { useRemoveAvatar, useUploadAvatar } from "./api";

const MAX_BYTES = 5 * 1024 * 1024;

export function AvatarEditor({ profile }: { profile: OwnProfile }) {
  const input = useRef<HTMLInputElement>(null);
  const upload = useUploadAvatar();
  const remove = useRemoveAvatar();
  const [tooLarge, setTooLarge] = useState(false);
  const busy = upload.isPending || remove.isPending;
  const failure = upload.error ?? remove.error;

  function onFile(file: File | undefined) {
    if (!file) {
      return;
    }
    remove.reset();
    upload.reset();
    // Same limit as the server; checked here to avoid a pointless upload.
    setTooLarge(file.size > MAX_BYTES);
    if (file.size <= MAX_BYTES) {
      upload.mutate(file);
    }
  }

  return (
    <div className="avatar-editor">
      <Avatar name={profile.display_name} url={profile.avatar_url} size={72} />
      <div>
        {tooLarge && <Notice kind="error">The image must be 5 MB or smaller.</Notice>}
        {failure && <Notice kind="error">{errorMessage(failure)}</Notice>}
        <input
          ref={input}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          className="visually-hidden"
          aria-label="Profile photo"
          onChange={(event) => {
            onFile(event.target.files?.[0]);
            event.target.value = "";
          }}
        />
        <div className="button-row">
          <button type="button" disabled={busy} onClick={() => input.current?.click()}>
            {upload.isPending ? "Uploading…" : profile.avatar_url ? "Change photo" : "Upload photo"}
          </button>
          {profile.avatar_url && (
            <button type="button" disabled={busy} onClick={() => remove.mutate()}>
              Remove
            </button>
          )}
        </div>
        <p className="field-hint">JPEG, PNG or WebP, up to 5 MB.</p>
      </div>
    </div>
  );
}
