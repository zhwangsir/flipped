// 极简内联 SVG 图标(stroke, currentColor)——不引图标库，保持轻与可控。
type P = { size?: number };
const b = (size = 16) => ({
  width: size,
  height: size,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
});

export const IconPlus = ({ size }: P) => (
  <svg {...b(size)}><path d="M12 5v14M5 12h14" /></svg>
);
export const IconTerminal = ({ size }: P) => (
  <svg {...b(size)}><rect x="3" y="4" width="18" height="16" rx="2" opacity="0.4" /><path d="M7 9l3 3-3 3M13 15h4" /></svg>
);
export const IconFile = ({ size }: P) => (
  <svg {...b(size)}><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5" /></svg>
);
export const IconFolder = ({ size }: P) => (
  <svg {...b(size)}><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /></svg>
);
export const IconBrowser = ({ size }: P) => (
  <svg {...b(size)}><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c2.5 2.5 2.5 15 0 18M12 3c-2.5 2.5-2.5 15 0 18" /></svg>
);
export const IconSearch = ({ size }: P) => (
  <svg {...b(size)}><circle cx="11" cy="11" r="7" /><path d="m20 20-3.2-3.2" /></svg>
);
export const IconSend = ({ size }: P) => (
  <svg {...b(size)}><path d="M12 19V5M6 11l6-6 6 6" /></svg>
);
export const IconGear = ({ size }: P) => (
  <svg {...b(size)}><circle cx="12" cy="12" r="3.2" /><path d="M12 2.5v3M12 18.5v3M4.2 7l2.6 1.5M17.2 15.5l2.6 1.5M4.2 17l2.6-1.5M17.2 8.5l2.6-1.5" /></svg>
);
export const IconCheck = ({ size }: P) => (
  <svg {...b(size)}><path d="M20 6 9 17l-5-5" /></svg>
);
export const IconSun = ({ size }: P) => (
  <svg {...b(size)}><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
);
export const IconMoon = ({ size }: P) => (
  <svg {...b(size)}><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>
);
export const IconClock = ({ size }: P) => (
  <svg {...b(size)}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>
);
export const IconSidebar = ({ size }: P) => (
  <svg {...b(size)}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16" /></svg>
);
export const IconCube = ({ size }: P) => (
  <svg {...b(size)}><path d="M21 8 12 3 3 8v8l9 5 9-5z" /><path d="M3 8l9 5 9-5M12 13v8" /></svg>
);
export const IconChat = ({ size }: P) => (
  <svg {...b(size)}><path d="M4 5h16a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H9l-4 4v-4H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z" /></svg>
);
export const IconGit = ({ size }: P) => (
  <svg {...b(size)}><circle cx="6" cy="6" r="2.5" /><circle cx="6" cy="18" r="2.5" /><circle cx="18" cy="9" r="2.5" /><path d="M6 8.5v7M18 11.5c0 3-3 3.5-6 3.5" /></svg>
);
export const IconPuzzle = ({ size }: P) => (
  <svg {...b(size)}><path d="M10 4a2 2 0 1 1 4 0h3v3a2 2 0 1 1 0 4v3h-3a2 2 0 1 0-4 0H7v-3a2 2 0 1 1 0-4V4z" /></svg>
);
export const IconAt = ({ size }: P) => (
  <svg {...b(size)}><circle cx="12" cy="12" r="4" /><path d="M16 8v5a2.5 2.5 0 0 0 5 0v-1a9 9 0 1 0-3.5 7" /></svg>
);
export const IconSparkle = ({ size }: P) => (
  <svg {...b(size)}><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" /><path d="M19 15l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z" /></svg>
);
export const IconChevronDown = ({ size }: P) => (
  <svg {...b(size)}><path d="m6 9 6 6 6-6" /></svg>
);
export const IconCode = ({ size }: P) => (
  <svg {...b(size)}><path d="m8 7-5 5 5 5M16 7l5 5-5 5M13 4l-2 16" /></svg>
);
export const IconEye = ({ size }: P) => (
  <svg {...b(size)}><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7z" /><circle cx="12" cy="12" r="2.6" /></svg>
);
export const IconWarn = ({ size }: P) => (
  <svg {...b(size)}><path d="M12 4 3 19h18z" /><path d="M12 10v4M12 17h.01" /></svg>
);
export const IconPlay = ({ size }: P) => (
  <svg {...b(size)}><path d="M7 4.5v15l12-7.5z" /></svg>
);
export const IconLayout = ({ size }: P) => (
  <svg {...b(size)}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M15 4v16" /></svg>
);
export const IconBolt = ({ size }: P) => (
  <svg {...b(size)}><path d="M13 3 4 14h6l-1 7 9-11h-6z" /></svg>
);
export const IconClip = ({ size }: P) => (
  <svg {...b(size)}><path d="M21 11.5 12.5 20a5 5 0 0 1-7-7l8-8a3.3 3.3 0 0 1 4.7 4.7l-8 8a1.7 1.7 0 0 1-2.4-2.4l7.6-7.6" /></svg>
);
export const IconStop = ({ size }: P) => (
  <svg {...b(size)}><rect x="6" y="6" width="12" height="12" rx="2.5" /></svg>
);
export const IconShield = ({ size }: P) => (
  <svg {...b(size)}><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /></svg>
);
export const IconX = ({ size }: P) => (
  <svg {...b(size)}><path d="M18 6 6 18M6 6l12 12" /></svg>
);
export const IconHourglass = ({ size }: P) => (
  <svg {...b(size)}><path d="M5 4h14M7 4v2a5 5 0 0 0 5 5 5 5 0 0 0 5-5V4M7 20h10M7 20v-2a5 5 0 0 1 5-5 5 5 0 0 1 5 5v2M12 11v2" /></svg>
);
export const IconCircleAlert = ({ size }: P) => (
  <svg {...b(size)}><circle cx="12" cy="12" r="10" /><path d="M12 8v4M12 16h.01" /></svg>
);
export const IconCheckCircle = ({ size }: P) => (
  <svg {...b(size)}><circle cx="12" cy="12" r="10" /><path d="m9 12 2 2 4-4" /></svg>
);
export const IconMore = ({ size }: P) => (
  <svg {...b(size)}><circle cx="5" cy="12" r="1" /><circle cx="12" cy="12" r="1" /><circle cx="19" cy="12" r="1" /></svg>
);
export const IconEdit = ({ size }: P) => (
  <svg {...b(size)}><path d="M12 20h9" /><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z" /></svg>
);
export const IconPin = ({ size }: P) => (
  <svg {...b(size)}><path d="M12 17v5" /><path d="M9 3h6l-1 7 3 3H7l3-3z" /></svg>
);
export const IconArchive = ({ size }: P) => (
  <svg {...b(size)}><rect x="3" y="4" width="18" height="4" rx="1" /><path d="M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8M10 12h4" /></svg>
);
export const IconChevronRight = ({ size }: P) => (
  <svg {...b(size)}><path d="m9 6 6 6-6 6" /></svg>
);

export function ToolIcon({ name, size = 15 }: { name: string; size?: number }) {
  if (name === "terminal") return <IconTerminal size={size} />;
  if (name === "browser") return <IconBrowser size={size} />;
  if (name === "search") return <IconSearch size={size} />;
  return <IconFile size={size} />;
}
