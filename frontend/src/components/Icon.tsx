const PATHS = {
  home: "M4 11.5 12 4l8 7.5M6.5 10v9.5h11V10M10 19.5v-5h4v5",
  compass: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM15.5 8.5l-2 5-5 2 2-5 5-2Z",
  people:
    "M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7ZM2.5 20c.4-3.6 3-5.5 6.5-5.5s6.100 1.900 6.500 5.500M16 4.300a3.500 3.500 0 0 1 0 6.400M18.500 14.800c1.800.700 2.800 2.400 3 5.200",
  building:
    "M5 20.500V5.500l8-2v17M13 9l6 1.500v10M3 20.500h18M8.500 8.500v0M8.500 12v0M8.500 15.500v0",
  briefcase:
    "M4 8h16a1 1 0 0 1 1 1v9.500a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1ZM9 8V5.500a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1V8M3 13h18",
  bell: "M6 16.500V11a6 6 0 1 1 12 0v5.500l1.500 2h-15l1.500-2ZM10 20.500a2 2 0 0 0 4 0",
  bookmark: "M7 4h10a1 1 0 0 1 1 1v15.500l-6-4-6 4V5a1 1 0 0 1 1-1Z",
  pencil: "M4 20l1-4.500L16.500 4l3.500 3.500L8.500 19 4 20ZM14 6.500l3.500 3.500",
  gear: "M12 15.500a3.500 3.500 0 1 0 0-7 3.500 3.500 0 0 0 0 7ZM12 2.500v3M12 18.500v3M2.500 12h3M18.500 12h3M5.300 5.300l2.100 2.100M16.600 16.600l2.100 2.100M5.300 18.700l2.100-2.100M16.600 7.400l2.100-2.100",
  megaphone: "M4 10v4l3 .500V9.500L4 10ZM7 9.500 19 5v14L7 14.500M9 15l1 4.500h2.500L11.500 15.500",
  logout: "M10 4H5.500a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1H10M15 8l4 4-4 4M19 12H9.500",
  chevron: "M6 9.500l6 6 6-6",
  spark: "M12 3l2.200 6.800L21 12l-6.800 2.200L12 21l-2.200-6.800L3 12l6.800-2.200L12 3Z",
  plus: "M12 5v14M5 12h14",
  flag: "M6 21V4M6 5h11l-2 3.500 2 3.500H6",
  shield:
    "M12 3.500 5 6v5.500c0 4.200 2.800 7.300 7 9 4.200-1.700 7-4.800 7-9V6l-7-2.500ZM9 12l2.200 2.200L15 10.500",
  chat: "M5 5h14a1 1 0 0 1 1 1v9.500a1 1 0 0 1-1 1h-6.500L8 20.500V16.500H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Z",
  calendar:
    "M5 6h14a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1ZM4 10.500h16M8 3.500v4M16 3.500v4",
  referral: "M4 12h13M12.500 6.500 18 12l-5.500 5.500M20.500 5v14",
  handshake:
    "M9 11a3.500 3.500 0 1 0 0-7 3.500 3.500 0 0 0 0 7ZM2.500 20c.400-3.600 3-5.500 6.500-5.500 1.600 0 3 .400 4.100 1.100M18 13.500v6M15 16.500h6",
} as const;

export type IconName = keyof typeof PATHS;

/** A line icon. Always decorative: the control it sits in carries the words. */
export function Icon({ name, size = 22 }: { name: IconName; size?: number }) {
  return (
    <svg
      className="icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
