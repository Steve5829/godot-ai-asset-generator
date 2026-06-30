# 生成方式演化记录 (Generation Approaches)

本文档记录这个生图插件尝试过的每一种"风格生成方式"。所有方式都被保留下来：
既可以在编辑器里通过 **Generation Mode 下拉框**实时切换对比，也可以在 git 历史里
回看每个阶段的实现。

> 在 Godot 里：右键文件夹 → `Vibe: Generate` → 选择 **Generation Mode**，
> 下拉框下方会显示当前模式的说明。

---

## 四种可选模式（当前插件内置）

| 模式 (Mode) | 做什么 | 适合 | 对应的尝试阶段 |
|---|---|---|---|
| **Plain text** | 只用文字 prompt + 写死的风格/材质描述生成，不用任何参考图 | 最稳定、最快，主体清晰 | 最初的"写死描述"方案 |
| **Reference analysis** | 用 GPT-4o 视觉分析匹配的参考图，把风格总结成文字，再加进 prompt | 想让风格更贴近参考、又保留主体 | 中期"参考图引导"方案 |
| **Style transfer** | 把匹配的参考图像素直接喂给 PixelLab (bitforge) 做风格迁移 | 方块/地表材质最像目标游戏 | 最新"图生图"方案 |
| **Auto (smart)** | 按资源类型自动选：方块/地表用 style transfer，图标用 reference analysis | 日常默认，自动取最优 | 三种方式的智能混合 |

---

## 每种方式的技术细节与关键 commit

### 1. Plain text —— 写死描述（最初方案）
- **思路**：每种材质/物品在代码里写一段固定的视觉描述（"深紫黑色火山玻璃"
  "金色金属带琥珀噪点"…），拼进 prompt 交给 PixelLab pixflux 文生图。
- **现状**：这些描述现在存在 `server/data/materials.json`（46 种方块）和
  `server/data/icons.json`（32 类图标）里，**Plain text 模式仍然在用它们**。
- **关键 commit**：
  - `5ae4918` Use profiled block face materials —— 引入材质描述档案
  - `ae92749` Constrain block face generation prompts —— 约束方块面描述
  - `04037d8` Add asset type image generation framework —— 整体框架
- **演示**：选 Plain text，生成 `obsidian block` / `healing potion`，
  描述里能看到写死的视觉文字。

### 2. Reference analysis —— 参考图文字引导（中期方案）
- **思路**：在 `reference_images/<游戏>/<类型>/` 放真实游戏素材，生成时用视觉模型
  分析这些图，总结出"色板/轮廓/材质"等文字特征，加进 prompt。参考图本身不进生成器。
- **关键 commit**：
  - `489fb11` Add reference image guidance —— 引入参考图分析
  - `a6b2019` Select reference images by prompt —— 按 prompt 匹配参考图
- **演示**：选 Reference analysis，生成图标类资源，后端日志会显示
  `references: analyzed (N)`。

### 3. Style transfer —— 图生图（最新方案）
- **思路**：把匹配的参考图像素直接作为 `style_image` 传给 PixelLab 的
  **bitforge** 端点，做真正的风格迁移，而不是只传文字。
- **关键 commit**：
  - `e97e800` Pass reference images to PixelLab as style guidance —— 接入 bitforge
  - `4765b89` Resize style image to match PixelLab output size —— 修尺寸匹配
  - `f93510b` Generate styled block faces at crisp integer-multiple sizes —— 修模糊
  - `009c8f6` Limit style transfer to material asset types —— 限制到材质类型
  - `3701d4d` Snap styled block faces to a tight palette —— 调色板量化去糊
- **已知特性**：对方块/地表材质效果好；对图标（如 zombie）会把主体盖成糊块，
  所以 Auto 模式默认不对图标用它（但显式选 Style transfer 时会，方便对比）。
- **演示**：选 Style transfer，生成 `diamond block`（minecraft），后端日志显示
  `Using style reference image for PixelLab generation`。

### 4. Auto —— 智能混合（当前默认）
- **思路**：综合以上，按资源类型选最优方式。
- **关键 commit**：
  - `94ea0da` Add selectable generation mode —— 引入模式选择
  - `ff8edb7` Show a description under the generation mode dropdown —— 模式说明

---

## 架构演化（让"加游戏 = 加文件"成为可能）

除了生成方式，代码结构也做了重构，使得新增游戏风格无需改 Python：

| 阶段 | commit | 成果 |
|---|---|---|
| 数据化分支 | `a01bc32` | 把写死的 if/else 分支搬进数据表 |
| 外置数据 | `cc8fb9d` `4420843` | 风格/材质/图标搬到 `packs/` 和 `data/` 的 JSON |
| 动态注册 | `fe12f6b` | 后端动态下发选项，编辑器下拉框自动更新 |
| 回归测试 | `1ee9dba` | `test_planner.py`(108) + `test_plan_snapshot.py`(9) 守护重构 |

**效果**：新增 Stardew 风格只需加 `packs/stardew.json` 一个文件（见 `8884a18`），
Python 一行未改，编辑器下拉框自动出现 Stardew。

---

## 如何对比演示

用**同一个 prompt + 同一个 Style Target**，依次切换四种 Generation Mode 生成，
把结果并排对比。推荐测试组合：

- `diamond block` × minecraft —— 看 Plain / Reference / Style transfer 的方块差异
- `healing potion` × core_keeper —— 看图标在各模式下的差异
- `forest ground` × stardew —— 看地表在各模式下的差异

后端日志每次会打印 `mode: xxx`，方便记录每张图用了哪种方式。
