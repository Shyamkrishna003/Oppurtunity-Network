import type { CSSProperties } from "react";

// Fixed rather than random, so rendering stays pure: [left %, delay ms, drift px, spin deg].
const PIECES = [
  [4, 0, 40, 540],
  [11, 180, -30, -420],
  [18, 60, 25, 610],
  [26, 260, -45, 380],
  [33, 20, 35, -560],
  [41, 140, -20, 470],
  [48, 300, 50, -390],
  [55, 90, -35, 620],
  [62, 220, 20, -480],
  [69, 40, -50, 530],
  [76, 170, 30, -600],
  [83, 280, -25, 410],
  [90, 110, 45, -520],
  [96, 240, -40, 580],
] as const;

/** A short burst of confetti over the page. Purely decorative, and skipped entirely for
 *  people who ask for reduced motion. */
export function Confetti() {
  return (
    <div className="confetti" aria-hidden="true">
      {PIECES.map(([x, delay, drift, spin]) => (
        <i
          key={x}
          style={{ "--x": x, "--d": delay, "--drift": drift, "--spin": spin } as CSSProperties}
        />
      ))}
    </div>
  );
}
