# AI UI 设计系统指令文档

> 用法：将本文档作为 system prompt 或参考文件喂给 AI（Cursor / v0 / Claude / ChatGPT）。
> 告知 AI："请严格遵循以下设计系统生成界面，不要自行发明颜色、字体或组件样式。"

---

## 1. 核心原则

1. **先定风格，再给需求。** 所有界面必须归属一种已命名风格（见第 2 节），禁止用 "clean and modern" 等模糊描述。
2. **颜色必须给 Hex 值。** 禁止说"蓝色"，要说 `#0066cc`。
3. **字体必须有字重和字号。** 标题/正文/标签分别指定 family、size、weight、line-height、letter-spacing。
4. **动效必须给专业术语。** 禁止"酷炫动画"，要说 `stagger fade-in with 100ms delay`。
5. **参考真实产品时给出品牌名。** 例如 "like Linear"、"like Stripe"、"like Apple"。
6. **组件必须有状态。** 至少包含 default / hover / active / focus / disabled。
7. **响应式必须写断点。** 默认覆盖 desktop / tablet / mobile。
8. **无障碍必须满足 WCAG AA。** 正文对比度 ≥ 4.5:1，大文本 ≥ 3:1。

---

## 2. 风格清单与提示词模板

### 2.1 极简主义 Minimalism
- **关键词**：whitespace-driven, neutral tones, single accent, generous padding, system font
- **主色**：`#0071E3`
- **背景**：`#FFFFFF` / `#FAFAFA`
- **文字**：`#1D1D1F` / `#86868B`
- **字体**：Inter / SF Pro Display
- **典型参考**：Apple, Linear, Notion
- **提示词**：
  > Scandinavian minimal style, white background #FFFFFF, generous whitespace (100-200px section gaps), Inter font, hero title 72px weight 800 in #1D1D1F, body 17px weight 300 in #86868B. Single accent #0071E3 for CTAs only. No shadows, no borders, content-first.

### 2.2 暗黑模式 Dark Mode
- **关键词**：near-black background, elevated surface ladder, brand glow, high contrast
- **背景**：`#0D0D12` / `#1A1A2E`
- **表面**：`#141516` / `#1E1E2E`
- **文字**：`#F5F5F5` / `#9E9E9E`
- **强调色**：`#0A84FF` / `#5E6AD2`
- **典型参考**：Linear, GitHub Dark, Vercel, Superhuman
- **提示词**：
  > Dark premium theme, canvas #0D0D12, surface #1A1A2E, text #F5F5F5, muted text #9E9E9E. Accent #0A84FF with glow effect `box-shadow: 0 0 20px rgba(10,132,255,0.3)`. Cards use subtle borders and surface lifts. Inter font, body 16px weight 400.

### 2.3 毛玻璃 / 液态玻璃 Glassmorphism
- **关键词**：backdrop-blur, translucent layers, border highlight, frosted glass
- **玻璃面板**：`rgba(255,255,255,0.1)` + blur 16px
- **边框**：`rgba(255,255,255,0.2)` 1px
- **背景**：鲜艳渐变或彩色图片
- **典型参考**：Apple iOS, Windows 11 Acrylic, Glassmorphism 营销页
- **提示词**：
  > Glassmorphism UI, rich gradient background, frosted glass panels with `backdrop-filter: blur(16px)`, `bg-white/10`, 1px border `rgba(255,255,255,0.2)`, rounded-2xl. White text on glass. Subtle shadows. Use as accent, not full layout.

### 2.4 Bento Box 网格布局
- **关键词**：modular cards, asymmetric grid, uniform gap, rounded corners, information density
- **背景**：`#F5F5F7`
- **卡片**：`#FFFFFF`
- **圆角**：16px
- **间距**：16px gap
- **典型参考**：Apple 产品页, Stripe, Linear
- **提示词**：
  > Apple-style Bento Grid, background #F5F5F7, white cards with rounded-2xl (16px), uniform 16px gap. Asymmetric grid with col-span cards. Cards hover lift `translateY(-2px)`. SF Pro Display, metric numbers 56px weight 800.

### 2.5 新拟态 Neumorphism
- **关键词**：soft extruded, dual shadows, pressed clay, low contrast
- **背景**：`#E0E5EC`
- **凸起阴影**：`8px 8px 16px #A3B1C6, -8px -8px 16px #FFFFFF`
- **凹陷阴影**：`inset 4px 4px 8px #A3B1C6, inset -4px -4px 8px #FFFFFF`
- **警告**：可访问性差，仅用于概念设计/作品集，不要用于生产环境。
- **提示词**：
  > Neumorphism style, base background #E0E5EC, all elements same color, distinguished only by dual soft shadows. Rounded-2xl. Inter font, low contrast #6B7280 text. For portfolio/concept only.

### 2.6 赛博朋克 Cyberpunk
- **关键词**：neon accents, terminal aesthetic, glitch effect, HUD, scan lines, dark canvas
- **背景**：`#0A0A0F`
- **霓虹青**：`#00FFF5`
- **霓虹粉**：`#FF0080`
- **霓虹绿**：`#00FF41`
- **字体**：JetBrains Mono / Rajdhani
- **典型参考**：Warp, Cyberpunk 2077, DeFi platforms
- **提示词**：
  > Cyberpunk terminal UI, background #0A0A0F, neon cyan #00FFF5 primary, neon pink #FF0080 secondary, toxic green #00FF41 success. JetBrains Mono for body, Rajdhani uppercase headings. Cut-corner clip-path panels, scan line overlay, glowing borders.

### 2.7 自然有机风 Organic
- **关键词**：organic curves, earth tones, paper texture, hand-drawn, botanical
- **背景**：`#FAF8F5`
- **主色**：Mocha Mousse `#A47F6C`
- **辅助**：Sage Green `#8B9E7E` / Mustard `#D4A843`
- **字体**：Lora / Playfair Display + 手写体
- **典型参考**：Kinfield, Apartamento Magazine, 有机食品品牌
- **提示词**：
  > Organic nature-inspired design, warm off-white #FAF8F5 background, Mocha Mousse #A47F6C primary, Sage Green #8B9E7E secondary. Serif headings italic, handwritten labels. Organic blob shapes, wavy dividers, botanical line illustrations, rounded-3xl cards.

### 2.8 复古怀旧风 Retro
- **关键词**：vintage gradients, pixel elements, serif/typwriter fonts, warm browns, grain texture
- **背景**：`#FDF6E3`
- **主色**：Burnt Orange `#C4622D` / Mustard `#D4A843`
- **辅助**：Olive Green `#5C7A4B` / Warm Red `#B54B4B`
- **字体**：Garamond / Caslon / Courier / Press Start 2P
- **典型参考**：Mountain Dew vintage, 网易云音乐复古活动页
- **提示词**：
  > Retro nostalgic design, cream #FDF6E3 background with grain texture, burnt orange #C4622D and mustard #D4A843 palette. Garamond/Courier typography, polaroid-style cards with slight rotation, tape decorations, thick borders.

### 2.9 粗野主义 Brutalism
- **关键词**：thick black strokes, hard shadows, high contrast, raw layout, system fonts
- **背景**：`#FFFFFF` / `#FFFF00`
- **边框**：3px solid `#000000`
- **阴影**：`4px 4px 0 #000`（无模糊）
- **字体**：Arial Black / Courier / Times New Roman
- **典型参考**：Bloomberg Businessweek, Balenciaga, Hype4 Agency
- **提示词**：
  > Neo-Brutalism design, alternating white and bright yellow #FFFF00 sections, thick 3px black borders, offset hard shadows `4px 4px 0 #000`. Arial Black uppercase headings, broken grid, overlapping elements, no rounded corners.

### 2.10 3D 沉浸式 Immersive
- **关键词**：CSS 3D transforms, parallax, depth layers, product showcase, scroll-triggered
- **背景**：深灰 `#111111`
- **强调色**：根据产品自定义（如金色 `#C9A96E`）
- **字体**：Inter weight 300-600
- **典型参考**：Tiffany & Co., Poltrona Frau, Apple 产品页
- **提示词**：
  > 3D immersive product showcase, dark charcoal background, centered 3D product with `perspective: 1200px`, mouse-follow rotation. Parallax layers at 0.2x/0.5x/1x speeds. Cards with 3D tilt on hover `translateZ(20px)`. Inter font, luxurious minimal UI.

---

## 3. 品牌级参考

AI 对以下品牌有强认知，提示词中直接引用品牌名可大幅提升一致性。

### 开发者工具
- **Linear**：极深画布 `#010102`，薰衣草蓝 `#5e6ad2`，紧凑信息密度，炭色卡片 + 细边框
- **Vercel**：黑白精准，Geist 字体，三角渐变
- **Cursor**：暗色界面，渐变强调色，现代 IDE
- **Warp**：现代终端，IDE 风格，块状命令 UI
- **Raycast**：暗色镀铬感，鲜艳渐变强调
- **Superhuman**：高端暗色 UI，键盘优先，紫色光晕

### SaaS / 生产力
- **Stripe**：靛蓝 `#533afd`，weight-300 Sohne 字体，渐变网格背景，金融表格用 `tnum`
- **Notion**：温暖极简，衬线标题，柔和表面
- **Intercom**：友好蓝色调，对话式 UI
- **Zapier**：暖橙色，插画驱动

### 消费科技
- **Apple**：极致留白，SF Pro 600 负字距，单一 Action Blue `#0066cc`，产品摄影优先
- **Spotify**：暗底上的鲜艳绿色，粗体排版，专辑封面驱动
- **SpaceX**：纯黑白，全出血图像，未来感
- **NVIDIA**：绿黑能量，技术力量感

### 金融科技
- **Revolut**：暗色界面，渐变卡片，金融精密
- **Coinbase**：干净蓝色，信任导向，机构感
- **Wise**：亮绿强调，友好清晰
- **Kraken**：紫色暗色 UI，数据密集仪表盘

### 汽车 / 奢侈品
- **Tesla**：极致减法，电影级全视口摄影
- **Bugatti**：纯黑画布，单色庄严，纪念性展示字体
- **Lamborghini**：纯黑教堂，金色强调，定制 Neo-Grotesk
- **Ferrari**：黑白编辑式，法拉利红极致克制

---

## 4. 动效关键词速查

### 滚动效果
| 中文 | 英文关键词 |
|------|-----------|
| 视差滚动 | parallax, depth layers, offset scrolling |
| 滚动渐现 | scroll reveal, fade in on scroll |
| 滚动叙事 | scrollytelling |
| 滚动吸附 | scroll snap |

### 悬停交互
| 中文 | 英文关键词 |
|------|-----------|
| 3D 倾斜（阻尼） | 3D tilt on hover, damped spring physics |
| 卡片抬起 | card lift, hover:translate-y-1 |
| 悬停发光 | hover glow |
| 涟漪效果 | ripple effect |
| 磁性光标 | magnetic cursor |

### 入场动画
| 中文 | 英文关键词 |
|------|-----------|
| 交错出现 | stagger, elements animate with small delays |
| 打字机 | typewriter, text appears char by char |
| 数字滚动 | counter, count up animation |
| 模糊渐入 | blur in, starts blurry sharpens |
| 弹入 | scale in, pop in, spring effect |
| 路径绘制 | draw / stroke, SVG path draws itself |

### 背景效果
| 中文 | 英文关键词 |
|------|-----------|
| 极光 | aurora, animated flowing gradients |
| 渐变网格 | gradient mesh, blurred color blobs |
| 粒子场 | particle field, floating dots |
| 噪点纹理 | noise / grain, subtle texture overlay |
| 扫描线 | scan line overlay |

---

## 5. PROMPT 六要素框架

每次写提示词时按以下结构组织：

1. **Platform & Device**：平台、设备、屏幕尺寸
2. **Role & User**：使用者画像、使用场景
3. **Output Specification**：具体组件、数据内容、页面元素
4. **Mood & Style**：设计风格名、配色方案、字体、整体氛围
5. **Patterns & Components**：导航模式、布局模式、组件库
6. **Technical Constraints**：框架、响应式、无障碍、暗色模式

### 万能模板

```text
Build a [STYLE NAME] [页面类型] for [产品类型].

Used by [目标用户], in [使用场景], to [目标结果].

Visual style:
- Design language: [Minimalism / Dark Mode / Glassmorphism / Bento Grid / Cyberpunk / etc.]
- Reference: "like [Brand Name]" if applicable
- Primary color: #XXXXXX
- Background: #XXXXXX
- Text color: #XXXXXX
- Font family: [Font Name]
- Headings: [size] / [weight] / [line-height] / [letter-spacing]
- Body: [size] / [weight] / [line-height]

Layout & components:
- [具体布局描述]
- [组件列表：导航、卡片、按钮、表单等]
- [交互状态：hover / active / focus / disabled]

Animations:
- [动效关键词，如 scroll reveal, stagger fade-in, hover lift]

Technical constraints:
- [HTML + Tailwind CSS / React + Tailwind / Vue]
- Mobile-first responsive
- WCAG AA compliant
- Use CSS variables for theme tokens
```

---

## 6. 参考网站清单

以下网站可直接用于"站在巨人肩膀上"——先看作品，再让 AI 参考其风格。

### 综合设计灵感
- [Awwwards](https://www.awwwards.com) — 获奖网站集合，完整网站案例
- [Godly Website](https://godly.website) — 新锐、实验性设计，AI/创意工具类
- [CSS Design Awards](https://www.cssdesignawards.com) — 偏向纯设计审美
- [Site Inspire](https://www.siteinspire.com) — 按 Hero / Typography / Layout 筛选
- [Lapa Ninja](https://www.lapa.ninja) — 落地页专用
- [One Page Love](https://onepagelove.com) — 单页网站
- [Minimal Gallery](https://minimal.gallery) — 极简主义校准
- [Dark Mode Design](https://www.darkmodedesign.com) — 顶级暗黑模式案例
- [Bento Grids](https://bentogrids.com) — Bento 网格布局参考
- [Landingfolio](https://www.landingfolio.com) — 落地页结构公式

### App / UI 设计灵感
- [Mobbin](https://mobbin.com) — 真实 App 完整流程截图
- [Pttrns](https://pttrns.com) — UI Pattern 库
- [Screenlane](https://screenlane.com) — App/Web UI 更新快
- [Refero](https://refero.design) — Web SaaS 控件结构命名参考
- [UIverse](https://uiverse.io) — 开源 CSS/Tailwind 组件

### 视觉与概念
- [Behance](https://www.behance.net) — 项目叙事、视觉体系、情绪氛围
- [Dribbble](https://dribbble.com) — 只看灵感，不看结构（多为飞机稿）

### AI 设计系统参考项目
- [awesome-design-md](https://github.com/VoltAgent/awesome-design-md) — 73 个真实网站的 DESIGN.md 设计系统
- [Google Stitch DESIGN.md](https://stitch.withgoogle.com/docs/design-md/overview/) — DESIGN.md 官方概念

### 品牌官网直接参考
| 风格 | 参考网站 |
|------|---------|
| 极简 / 科技 | Apple, Linear, Notion, Vercel |
| 暗黑高端 | Linear, Superhuman, Raycast, Warp |
| 毛玻璃 | Apple iOS, Windows 11 Fluent |
| Bento Grid | Apple 产品页, Stripe, Linear |
| 赛博朋克 | Warp Terminal, Cyberpunk 2077, DeFi 平台 |
| 自然有机 | Kinfield, Apartamento Magazine |
| 复古怀旧 | Mountain Dew vintage, 网易云音乐复古页 |
| 粗野主义 | Bloomberg Businessweek, Balenciaga, Hype4 |
| 3D 沉浸 | Tiffany & Co., Poltrona Frau, Apple 产品页 |
| 金融科技 | Stripe, Revolut, Coinbase, Wise |

---

## 7. 使用示例

### 示例 1：极简 SaaS 落地页

```text
Build a Scandinavian minimal SaaS landing page for a productivity tool.

Visual style:
- Like Apple product page but simpler
- Background #FFFFFF, section gaps 120px
- Primary #0071E3, text #1D1D1F, muted #86868B
- Inter font, hero 64px weight 700 -0.02em tracking, body 17px weight 400 1.6 line-height

Components:
- Top nav: 4 links + primary CTA pill
- Hero: centered headline + subhead + two pill CTAs
- 3 feature cards: icon + title + description, no border, no shadow
- Footer: dense link columns on #F5F5F7

Animations:
- Scroll reveal with stagger 100ms
- Button hover: scale(1.02)

Constraints:
- HTML + Tailwind CSS
- Mobile-first, max-width 1200px
- WCAG AA compliant
```

### 示例 2：Linear 风格仪表盘

```text
Build a Linear-style dark analytics dashboard for a developer tool.

Visual style:
- Like Linear — canvas #010102, surface #0f1011, hairline borders #23252a
- Lavender accent #5e6ad2, hover #828fff
- Inter font, display weight 600 with negative tracking, body 16px weight 400

Components:
- Left sidebar 240px, dark, icon + label nav
- Top bar: search + notifications + user avatar
- 4 metric cards: surface-1, rounded-lg, hairline border, large metric number
- 1 area chart: gradient fill from accent to transparent
- Recent activity table: compact rows, mono for IDs

Animations:
- Cards stagger fade-in on load
- Hover: surface lift to surface-2
- Button press: scale(0.97)

Constraints:
- React + Tailwind CSS
- Dark mode only
- CSS variables for all tokens
- WCAG AA
```

### 示例 3：Stripe 风格金融科技页

```text
Build a Stripe-inspired payment infrastructure landing page.

Visual style:
- Like Stripe — indigo #533afd, deep navy ink #0d253d, cream canvas
- Weight-300 Sohne/Inter typography with negative tracking
- Gradient mesh backdrop across top third
- Tabular figures `font-feature-settings: "tnum"` for all money/numeric cells

Components:
- Nav floating over gradient mesh, white bg
- Hero: thin display headline + subhead + indigo pill CTA
- Feature cards on white with subtle shadow
- Dashboard mockup: faux IDE + table + chart composite
- Pricing cards: 3 tiers, featured tier on deep navy #1c1e54

Animations:
- Gradient mesh subtle drift
- Cards fade up on scroll with stagger
- Buttons: press state to deeper indigo #2e2b8c

Constraints:
- HTML + Tailwind CSS
- Responsive 4/2/1 pricing grid
- WCAG AA
```

---

## 8. 禁止事项

- 禁止说 "clean and modern" / "beautiful" / "professional"
- 禁止不给 Hex 色值
- 禁止不给字体规格
- 禁止不给响应式策略
- 禁止发明未指定的颜色或字体
- 禁止默认使用圆角阴影（必须按风格规则）
- 禁止忽略无障碍对比度

---

## 9. 输出检查清单

生成完成后，AI 必须自检：

- [ ] 风格名称是否明确？
- [ ] 所有颜色是否有 Hex 值？
- [ ] 字体规格是否完整（family/size/weight/line-height/letter-spacing）？
- [ ] 组件是否包含 default/hover/active/focus/disabled？
- [ ] 是否有响应式策略？
- [ ] 是否满足 WCAG AA 对比度？
- [ ] 动效是否使用专业术语？
- [ ] 是否有真实品牌参考（可选但推荐）？
