export function Splash({ label = "Loading…" }: { label?: string }) {
  return (
    <p className="splash muted" role="status">
      <span className="loader" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
      {label}
    </p>
  );
}
