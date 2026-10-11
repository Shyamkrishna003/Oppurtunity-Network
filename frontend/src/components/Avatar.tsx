import type { CSSProperties } from "react";

const COLOURS = ["--sun", "--pink", "--mint", "--sky", "--peach"];

/** The same name always gets the same colour, so people are recognisable at a glance. */
function colourFor(name: string): string {
  let sum = 0;
  for (const character of name) {
    sum += character.codePointAt(0) ?? 0;
  }
  return `var(${COLOURS[sum % COLOURS.length] ?? "--peach"})`;
}

export function Avatar({
  name,
  url,
  size = 40,
  square = false,
}: {
  name: string;
  url: string | null;
  size?: number;
  /** For organizations and other things that are not a person. */
  square?: boolean;
}) {
  const shape = square ? " avatar-square" : "";
  const style = { width: size, height: size, fontSize: size * 0.42 };
  if (url) {
    // Decorative: the name is always shown next to it.
    return <img className={`avatar${shape}`} src={url} alt="" style={style} />;
  }
  return (
    <span
      className={`avatar avatar-initial${shape}`}
      style={{ ...style, "--avatar": colourFor(name) } as CSSProperties}
      aria-hidden="true"
    >
      {name.trim().charAt(0).toUpperCase() || "?"}
    </span>
  );
}
