import { useEffect, useRef, useState } from "react";

/** The part of the browser's barcode reader this uses. Not every browser has one. */
interface Detector {
  detect(source: HTMLVideoElement): Promise<{ rawValue: string }[]>;
}
type DetectorClass = new (options: { formats: string[] }) => Detector;

function detectorClass(): DetectorClass | null {
  const found = (globalThis as { BarcodeDetector?: DetectorClass }).BarcodeDetector;
  return typeof found === "function" && Boolean(navigator.mediaDevices) ? found : null;
}

const SCAN_EVERY_MS = 300;
// Holding a code in view must not send it again and again.
const SAME_CODE_AGAIN_MS = 4000;

/**
 * Reads QR codes with the device's camera and hands each one to `onCode`.
 *
 * Renders nothing in a browser that cannot read codes: the page's code box still works
 * there. The picture never leaves the device; only the text of a code is passed on.
 */
export function CameraScanner({ onCode }: { onCode: (code: string) => void }) {
  const [Reader] = useState(detectorClass);
  const [on, setOn] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const video = useRef<HTMLVideoElement>(null);
  const deliver = useRef(onCode);
  useEffect(() => {
    deliver.current = onCode;
  }, [onCode]);

  useEffect(() => {
    if (!on || !Reader) {
      return;
    }
    let stream: MediaStream | null = null;
    let timer: ReturnType<typeof setInterval> | undefined;
    let stopped = false;
    let last = { code: "", at: 0 };

    void (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "environment" },
        });
      } catch {
        setProblem("The camera could not be used. Allow it for this site, or enter the code.");
        setOn(false);
        return;
      }
      if (stopped || !video.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      video.current.srcObject = stream;
      await video.current.play().catch(() => undefined);
      const reader = new Reader({ formats: ["qr_code"] });
      timer = setInterval(() => {
        if (!video.current) {
          return;
        }
        void reader
          .detect(video.current)
          .then((found) => {
            const code = found[0]?.rawValue;
            const now = Date.now();
            if (code && (code !== last.code || now - last.at > SAME_CODE_AGAIN_MS)) {
              last = { code, at: now };
              deliver.current(code);
            }
          })
          .catch(() => undefined); // a frame that could not be read: try the next
      }, SCAN_EVERY_MS);
    })();

    return () => {
      stopped = true;
      clearInterval(timer);
      stream?.getTracks().forEach((track) => track.stop());
    };
  }, [on, Reader]);

  if (!Reader) {
    return null;
  }
  return (
    <div className="scanner">
      <button
        type="button"
        aria-pressed={on}
        onClick={() => {
          setProblem(null);
          setOn((value) => !value);
        }}
      >
        {on ? "Stop camera" : "Scan with camera"}
      </button>
      {problem && (
        <p className="field-error" role="alert">
          {problem}
        </p>
      )}
      {on && <video ref={video} className="scanner-view" muted playsInline aria-label="Camera" />}
    </div>
  );
}
