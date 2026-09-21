// 统一图标源：lucide-react（项目硬性规则：唯一图标库，禁止自定义 SVG/emoji 图标）。
// 本文件仅做薄封装：保留既有导出名与 size API，调用点（22 个组件）零改动。
// 统一 strokeWidth=1.6 对齐原视觉；aria-hidden 默认 true（装饰性图标，语义由父元素承担）。
import type { LucideIcon } from "lucide-react";
import {
  Plus,
  Terminal,
  File,
  Folder,
  Globe,
  Search,
  Send,
  Settings,
  Check,
  Sun,
  Moon,
  Clock,
  PanelLeft,
  Box,
  MessageSquare,
  GitBranch,
  Puzzle,
  AtSign,
  Sparkles,
  ChevronDown,
  Code,
  Eye,
  TriangleAlert,
  Play,
  PanelRight,
  Zap,
  Paperclip,
  Square,
  Shield,
  X,
  Hourglass,
  CircleAlert,
  CircleCheck,
  MoreHorizontal,
  Pencil,
  Pin,
  Archive,
  ChevronRight,
  ChevronLeft,
  SquareKanban,
  Factory,
  Pause,
  RefreshCw,
  Map,
  Target,
  Smartphone,
  Bot,
  Wand2,
  ImagePlus,
  ScrollText,
} from "lucide-react";

type P = { size?: number };

const w = (Icon: LucideIcon) =>
  function FlippedIcon({ size }: P) {
    return <Icon size={size ?? 16} strokeWidth={1.6} aria-hidden={true} />;
  };

export const IconPlus = w(Plus);
export const IconTerminal = w(Terminal);
export const IconFile = w(File);
export const IconFolder = w(Folder);
export const IconBrowser = w(Globe);
export const IconSearch = w(Search);
export const IconSend = w(Send);
export const IconGear = w(Settings);
export const IconCheck = w(Check);
export const IconSun = w(Sun);
export const IconMoon = w(Moon);
export const IconClock = w(Clock);
export const IconSidebar = w(PanelLeft);
export const IconCube = w(Box);
export const IconChat = w(MessageSquare);
export const IconGit = w(GitBranch);
export const IconPuzzle = w(Puzzle);
export const IconAt = w(AtSign);
export const IconSparkle = w(Sparkles);
export const IconChevronDown = w(ChevronDown);
export const IconCode = w(Code);
export const IconEye = w(Eye);
export const IconWarn = w(TriangleAlert);
export const IconPlay = w(Play);
export const IconLayout = w(PanelRight);
export const IconBolt = w(Zap);
export const IconClip = w(Paperclip);
export const IconStop = w(Square);
export const IconShield = w(Shield);
export const IconX = w(X);
export const IconHourglass = w(Hourglass);
export const IconCircleAlert = w(CircleAlert);
export const IconCheckCircle = w(CircleCheck);
export const IconMore = w(MoreHorizontal);
export const IconEdit = w(Pencil);
export const IconPin = w(Pin);
export const IconArchive = w(Archive);
export const IconChevronRight = w(ChevronRight);
export const IconChevronLeft = w(ChevronLeft);
export const IconReview = w(SquareKanban);
export const IconFactory = w(Factory);
export const IconPause = w(Pause);
export const IconRefresh = w(RefreshCw);
export const IconMap = w(Map);
export const IconTarget = w(Target);
export const IconSmartphone = w(Smartphone);
export const IconBot = w(Bot);
export const IconWand = w(Wand2);
export const IconImagePlus = w(ImagePlus);
export const IconScrollText = w(ScrollText);

export function ToolIcon({ name, size = 15 }: { name: string; size?: number }) {
  if (name === "terminal") return <IconTerminal size={size} />;
  if (name === "browser") return <IconBrowser size={size} />;
  if (name === "search") return <IconSearch size={size} />;
  return <IconFile size={size} />;
}
