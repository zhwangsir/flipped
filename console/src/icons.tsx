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
  // D-0009 修复：装饰性 SVG 统一 aria-hidden，避免屏幕阅读器读出 <path> 数据。
  // 父按钮若有 aria-label/title，SVG 自动被忽略；裸 SVG 也由此覆盖。
  // 用 boolean true（非字符串 "true"）满足 SVGProps Booleanish 类型约束；
  // key 必须用连字符 "aria-hidden"（React 不转换 aria* camelCase，会渲染成 ariahidden）。
  "aria-hidden": true as const,
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
export const IconChevronLeft = ({ size }: P) => (
  <svg {...b(size)}><path d="m15 6-6 6 6 6" /></svg>
);
export const IconReview = ({ size }: P) => (
  <svg {...b(size)}><rect x="4" y="4" width="16" height="16" rx="2" /><path d="M8 9h4M8 9v6M15 8v8M13 12h4" /></svg>
);
export const IconFactory = ({ size }: P) => (
  <svg {...b(size)}><path d="M3 21V8l6 4V8l6 4V8l6 4v9z" /><path d="M3 21h18M9 13v4M15 13v4" /></svg>
);
export const IconPause = ({ size }: P) => (
  <svg {...b(size)}><rect x="6" y="5" width="4" height="14" rx="1" /><rect x="14" y="5" width="4" height="14" rx="1" /></svg>
);
export const IconRefresh = ({ size }: P) => (
  <svg {...b(size)}><path d="M3 12a9 9 0 0 1 15-6.7L21 8M21 3v5h-5M21 12a9 9 0 0 1-15 6.7L3 16M3 21v-5h5" /></svg>
);
export const IconMap = ({ size }: P) => (
  <svg {...b(size)}><path d="M9 3 2 6v15l7-3 6 3 7-3V3l-7 3z" /><path d="M9 3v15M15 6v15" /></svg>
);
// M176 — Goal 模式 marker(lucide Target 同款:三同心圆靶心)
export const IconTarget = ({ size }: P) => (
  <svg {...b(size)}><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" /><circle cx="12" cy="12" r="1" /></svg>
);
// M181.2 — 移动远程控制(lucide Smartphone 同款:圆角机身 + 底部 home 短线)
export const IconSmartphone = ({ size }: P) => (
  <svg {...b(size)}><rect x="7" y="2" width="10" height="20" rx="2" /><path d="M11 18h2" /></svg>
);
// M182 — Bot 通道(lucide Bot 同款:天线 + 矩形脸 + 两眼)
export const IconBot = ({ size }: P) => (
  <svg {...b(size)}><path d="M12 8V4h2" /><rect x="4" y="8" width="16" height="12" rx="2" /><path d="M2 14h2M20 14h2M9 13v2M15 13v2" /></svg>
);
// M183 — Worker 规则自动生成(lucide Wand2 同款:魔杖斜线 + 三点星光)
export const IconWand = ({ size }: P) => (
  <svg {...b(size)}><path d="m6 21 15-15-3-3L3 18z" /><path d="M14 7l3 3M9 2v2M4 7H2M7 11 5 13" /></svg>
);
// M192 — 图像附件(lucide ImagePlus 同款:图片框 + 右上加号)
export const IconImagePlus = ({ size }: P) => (
  <svg {...b(size)}><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7" /><path d="M16 5h6M19 2v6" /><circle cx="9" cy="9" r="2" /><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21" /></svg>
);
// M194.6 — Launcher 规则入口(lucide ScrollText 同款:卷轴 + 文本行)
export const IconScrollText = ({ size }: P) => (
  <svg {...b(size)}><path d="M19 17V5a2 2 0 0 0-2-2H4" /><path d="M8 21h12a2 2 0 0 0 2-2v-1a1 1 0 0 0-1-1H11a1 1 0 0 0-1 1v1a2 2 0 1 1-4 0V5a2 2 0 1 0-4 0v2a1 1 0 0 0 1 1h3" /><path d="M15 8h-5M15 12h-5" /></svg>
);

export function ToolIcon({ name, size = 15 }: { name: string; size?: number }) {
  if (name === "terminal") return <IconTerminal size={size} />;
  if (name === "browser") return <IconBrowser size={size} />;
  if (name === "search") return <IconSearch size={size} />;
  return <IconFile size={size} />;
}
