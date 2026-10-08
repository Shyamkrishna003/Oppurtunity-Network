export function Avatar({
  name,
  url,
  size = 40,
}: {
  name: string;
  url: string | null;
  size?: number;
}) {
  const style = { width: size, height: size, fontSize: size * 0.42 };
  if (url) {
    // Decorative: the name is always shown next to it.
    return <img className="avatar" src={url} alt="" style={style} />;
  }
  return (
    <span className="avatar avatar-initial" style={style} aria-hidden="true">
      {name.trim().charAt(0).toUpperCase() || "?"}
    </span>
  );
}
