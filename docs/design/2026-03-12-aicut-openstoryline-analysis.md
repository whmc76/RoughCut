# RoughCut 对比分析：AIcut / FireRed-OpenStoryline

日期：2026-03-12

## 结论

这两个项目都值得研究，但都不适合直接整体并入 RoughCut。

- `AIcut` 适合借鉴的是“可编辑时间轴 + AI 对时间轴做增量修改”的交互层。
- `FireRed-OpenStoryline` 适合借鉴的是“节点化能力编排 + Skill 沉淀 + 素材/BGM/风格库”的能力组织方式。
- 对 RoughCut 当前“口播/开箱视频自动粗剪”主线最有价值的改进，不是整仓迁移，而是分阶段吸收其中的 4 类能力：
  - 可视化时间轴复核与微调
  - B-roll / 插入素材 / BGM 推荐
  - 风格化模板与可复用 Skill
  - 对话式精修

## 当前 RoughCut 的定位

RoughCut 现在是“语音驱动的自动粗剪流水线”，强项是：

- 上传视频后自动完成探测、转写、术语纠错、剪辑决策、渲染、平台文案。
- 有状态机、数据库、断点续跑、任务面板、目录监听。
- 已经有一套适合口播/开箱内容的审校链路，以及包装素材库入口。

它的短板也很明确：

- 缺少真正可编辑、可预览、可回写的时间轴 UI。
- BGM、插入素材、镜头节奏、风格模板能力还比较轻。
- “用户一句话继续改”这类交互式精修能力还不强。

## AIcut 分析

### 它是什么

AIcut 是一个“前端编辑器优先”的系统，核心是：

- Next.js + Electron + Remotion 的编辑器壳
- Python SDK 通过 API 或 JSON 快照直接修改时间轴
- 前端监听快照变化，做到 AI 写入后立刻可视化

### 对 RoughCut 有帮助的点

1. `project-snapshot.json` 这一类稳定数据契约很有价值。
   RoughCut 现在已经有 `Timeline`、`RenderPlan`、`OTIO` 导出，天然适合再补一层“编辑器时间轴 JSON”。

2. AI 对时间轴做“增量修改”而不是“整段重算”，适合人工复核场景。
   例如：
   - 删除第 3 个口头禅片段
   - 第 25 秒后插入一段包装素材
   - 把字幕样式切到 `clean_box`

3. AIcut 的多轨思路能补足 RoughCut 当前只偏“保留/删除”决策的问题。
   RoughCut 已有包装素材库，下一步可以自然扩展到：
   - `video_main`
   - `subtitle`
   - `bgm`
   - `insert`
   - `watermark`

### 不建议直接集成的点

1. 技术栈差异过大。
   AIcut 的核心价值在 Electron/Next/Remotion 编辑器，和 RoughCut 当前 FastAPI 内嵌静态面板不是一个层级。

2. 它偏“通用创作编辑器”，不是“口播粗剪流水线”。
   直接搬入会把项目重心从自动化生产拉向编辑器产品化，成本很高。

3. 它的文件驱动同步依赖较重的本地路径模型。
   RoughCut 当前已经围绕数据库 + S3/MinIO + Job Artifact 建好了更稳定的后端结构，不应倒退成单文件同步为主。

### 对 RoughCut 的建议吸收方式

- 不搬 AIcut 前端。
- 借鉴它的数据契约思路，在 RoughCut 内新增“Editor Timeline JSON”层。
- 让 AI 精修针对这个 JSON 做 patch，而不是直接改最终 render 逻辑。

## FireRed-OpenStoryline 分析

### 它是什么

FireRed-OpenStoryline 是一个“对话式视频 Agent”系统，核心是：

- LangChain Agent + MCP Server
- 节点化视频流程
- 技能加载与沉淀
- 素材搜索、镜头理解、BGM 选择、脚本/配音/时间线生成

### 对 RoughCut 有帮助的点

1. 节点化能力组织方式非常值得借鉴。
   RoughCut 已经有 pipeline steps，但现在还是偏固定流水线。OpenStoryline 的 node / prereq / next-node 机制更适合扩展“可选能力”。

2. BGM 推荐和节拍对齐值得吸收。
   对开箱/展示类视频，单纯去静音不够，BGM 选择和节奏同步可以明显提升成片完成度。

3. Skill 机制很适合 RoughCut 的频道化生产。
   RoughCut 已经有：
   - `channel_profile`
   - `content_profile_memory`
   - `packaging library`

   这三者本身就接近 Skill 的雏形，只差一个显式“风格模板/规则包”的层。

4. 对话式精修是很强的产品增量。
   用户在审阅阶段说：
   - “把这条做得更像测评，不要像导购”
   - “插一段开箱细节近景在前 20 秒”
   - “BGM 再克制一点”

   这比重新全量跑流水线更符合真实使用场景。

### 不建议直接集成的点

1. LangChain + MCP + SkillKit 全栈接入成本较高。
   RoughCut 现在的 provider 抽象已经够轻，直接整体接入会明显增加复杂度和运维面。

2. 它更偏“从素材讲故事”，而不是“从单条口播做粗剪”。
   RoughCut 的主战场是 speech-first editing，不应该被拖成另一套产品。

3. 资源库依赖较重。
   OpenStoryline 很多效果依赖自建字体、BGM、模板库；这些能力有价值，但应该作为 RoughCut 的可选资产库模块引入，而不是先引它的框架。

### 对 RoughCut 的建议吸收方式

- 不直接引 LangChain Agent 主体。
- 借鉴它的节点元数据和 Skill 组织思路。
- 先在 RoughCut 内把“包装素材 / 音乐 / 字幕样式 / 标题风格”统一成显式模板系统。

## 对当前剪辑方案的直接帮助

结论是“有帮助，而且是结构性帮助”，但方向必须收敛。

### 最值得优先做的 4 项

1. 编辑器时间轴层
   目标：把现有 `editorial timeline + render plan` 升级成可视化、可 patch 的时间轴表示。

2. 插入素材与 B-roll 编排
   RoughCut 已有 `packaging.library` 和 LLM 选插入点逻辑，下一步可以扩展为多候选素材、多插入策略、多轨控制。

3. BGM 推荐与节拍化时间线
   借鉴 OpenStoryline 的 `select_bgm` 和 beat-aware timeline，但只保留对 RoughCut 有用的部分。

4. Skill / Preset 体系
   将现有这些能力合并：
   - `channel_profile`
   - `content_profile_memory`
   - `packaging config`
   - 字幕样式
   - 插入素材策略

   输出成可保存、可复用的 RoughCut Skill。

## 不建议现在做的事

- 不建议把 AIcut 整个 Electron/Next 编辑器嵌进来。
- 不建议把 OpenStoryline 的 LangChain + MCP 主体直接作为 RoughCut 主执行框架。
- 不建议为了“支持 npm”而把当前静态 Dashboard 强行改造成前后端分离项目。

原因很简单：这些都会把项目复杂度一次性抬太高，但不直接提升你现在最关心的“口播/开箱自动剪辑质量”。

## 推荐路线

### Phase 1：保持 RoughCut 为主，补足生产力层

- 新增 `uv + Docker Compose` 标准化安装/部署
- 补 `Editor Timeline JSON`
- 强化包装素材库为“可插入多资产库”
- 新增 BGM 资产与简单推荐逻辑

### Phase 2：做可复用风格系统

- 引入 RoughCut Skill / Preset
- 允许不同频道、不同题材切换模板
- 将字幕样式、片头片尾、封面风格、插入素材策略收敛成模板

### Phase 3：做对话式精修

- 用户对单个 Job 下达自然语言修改
- 系统只 patch timeline / packaging config，不重跑整条链路

### Phase 4：再决定是否要独立前端

- 如果确实要走“编辑器产品”，再上 React/Next + `pnpm workspace`
- 在那之前，`uv` 应该是主安装入口，npm 不是

## 最终判断

- `AIcut`：更适合作为“交互层/编辑器层”的参考样板
- `FireRed-OpenStoryline`：更适合作为“能力组织/Skill/BGM/素材编排层”的参考样板
- 对 RoughCut 最优策略：吸收思想和局部实现，不做整体并仓

这条路线既能提升当前粗剪方案质量，也不会把仓库复杂度一次性推到不可控。
