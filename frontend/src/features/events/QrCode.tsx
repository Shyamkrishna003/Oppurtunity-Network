import qrcode from "qrcode-generator";
import { useMemo } from "react";

// The quiet zone scanners expect around a code, in modules.
const MARGIN = 4;

/**
 * A QR code for `value`, drawn as an SVG.
 *
 * Always dark on white, whatever the theme: a scanner needs the contrast, and many cannot
 * read a light code on a dark background.
 */
export function QrCode({
  value,
  label,
  size = 240,
}: {
  value: string;
  label: string;
  size?: number;
}) {
  const { path, count } = useMemo(() => {
    const code = qrcode(0, "M");
    code.addData(value);
    code.make();
    const modules = code.getModuleCount();
    let d = "";
    for (let row = 0; row < modules; row += 1) {
      for (let column = 0; column < modules; column += 1) {
        if (code.isDark(row, column)) {
          d += `M${String(column + MARGIN)} ${String(row + MARGIN)}h1v1h-1z`;
        }
      }
    }
    return { path: d, count: modules + MARGIN * 2 };
  }, [value]);

  return (
    <svg
      className="qr"
      role="img"
      aria-label={label}
      width={size}
      height={size}
      viewBox={`0 0 ${String(count)} ${String(count)}`}
      shapeRendering="crispEdges"
    >
      <rect width={count} height={count} fill="#ffffff" />
      <path d={path} fill="#000000" />
    </svg>
  );
}
