export function Splash({ label = "Loading…" }: { label?: string }) {
  return (
    <p className="splash muted" role="status">
      {label}
    </p>
  );
}
