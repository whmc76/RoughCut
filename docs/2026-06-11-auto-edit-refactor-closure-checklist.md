# 自动剪辑重构优化与收口目标清单

日期：2026-06-11

## 目标定义

本清单用于收口 RoughCut 自动剪辑主链的重构工作，目标不是继续扩散式修补，而是把系统推进到以下状态：

- 自动剪辑主链稳定性达到 `85-90/100`
- 真实任务可用性达到 `80-88/100`
- 纯自动成片质量达到 `75-85/100`
- 人工复核后的交付质量达到 `88-92/100`

## 完成标准

当且仅当以下条件同时满足，才可认为“本轮主要框架改造已完成，进入质量增强阶段”：

1. `manual-editor`、`auto-edit`、`render` 三条主链不再存在隐藏串写和事实层污染。
2. `raw / canonical / display` 三层文本消费者完成主链收口，并有合同回归保护。
3. 规则候选生成、自动应用、人工阻断三者走统一注册表和统一风险分层。
4. `run_render` 与 batch runner 的阻塞、超时、失败终态、审计字段可完整回放。
5. golden set、评分卡、回归门禁能支撑“版本分数是否提升”的持续判断。

## 执行边界

本轮目标是完成自动剪辑主链的重构收口，不是无边界地继续加功能。执行边界定义如下：

- 只处理会影响 `manual-editor`、`auto-edit`、`render`、`packaging/review` 主链稳定性、可解释性、可回放性的结构问题。
- 优先修共享抽象、共享 contract、共享运行时边界，不优先做孤立业务分支的局部修补。
- 只有在 `C1-C5` 达到阶段验收后，`C6` 才进入主任务；在此之前，智能删减增强不得重新引入隐藏阶段、副作用链或未审计自动删除。
- 发布、平台运营、封面创意、文案风格等产出质量问题，只有在它们暴露共享合同缺陷、运行时边界缺陷或门禁缺失时，才属于本轮收口范围。
- 不以“单次样本看起来更好”作为完成依据；所有阶段都必须以合同回归、真实任务锚点、batch/golden 报表或可复放 smoke 为验收证据。

## 策略收缩：精简实用链路

从 2026-06-12 起，本轮收口按“高效、简洁、实用”的自动剪辑链路执行，不再继续扩成大而全的治理系统。

保留的最小主链：

1. `align`：ASR、字幕、时间轴对齐。
2. `propose`：生成删减候选，并标出来源和风险。
3. `apply`：只自动应用低风险候选，高风险进入人工确认。
4. `review`：manual editor 只做复核和微调，不重新跑隐式自动链。
5. `render`：渲染能完成、失败能终止、降级原因可看懂。
6. `accept`：用少量真实锚点和最小 scorecard 判断能不能交付。

停止继续扩展的内容：

- 不再新增 scorecard 字段，除非真实自动剪辑结果无法解释。
- 不再新增 golden manifest 元数据，除非真实锚点无法复跑。
- 不再扩展发布、封面、平台运营相关能力，除非它直接阻塞自动剪辑主链。
- 不再为单个边缘样本创建新抽象；先用现有 helper 或直接修主链边界。
- 不再追求 C1-C6 每项“完全体系化”，先完成可运行、可复核、可交付的阶段 B。

当前验收口径收缩为：

- 自动对齐剪辑能在真实锚点上稳定跑到 `edit_plan`。
- 低风险自动删减和高风险人工确认的数量能对上。
- manual editor 保存不会冲掉已接受自动删减。
- render 不挂死，失败或降级原因能直接看懂。
- manual editor 的 `no_material_change` 保存不再伪装成一次完整 `render` 重跑，而是只刷新必要的下游平台文案链路。
- 报告只保留交付判断需要的核心指标：质量分、阻断码、高风险数、人工确认数、render 终态。
- 对 `stop_after` 的 partial replay，不再复用完整发布的 `stable_runs >= 3` 门禁；主链阶段验收按 `1/1` 稳定回放判定即可。
- 对 `edit_plan` 已自动应用的删减，report/scorecard 必须显示 refine 后的有效 `keep_ratio / accepted_cuts`，不能再回退到 pre-refine `editorial_timeline` 旧口径。
- 对 `edit_plan` 的运行时恢复说明（例如 `audio_artifact_rebuilt`），应保留可见诊断但不得自动降成主链失败式 stage 评分。
- 对 auto mode 的低风险自动删减，下游若需要“最终已应用删减集合”，必须走共享 applied-cut helper，不能再把 `accepted_cuts` 误当成唯一事实层。
- manual editor session 若要切到 source fallback，必须在 validation 前先确定唯一显示基线；不允许再出现“先校验一版、再显示另一版”的隐式双轨。
- manual-editor/apply 的 subtitle-only 提交必须在 endpoint 级保持同一口径：`change_scope=subtitle_only`、`rerun issue_code=manual_subtitle_edit`、`refine_decision_plan.keep_segments=effective_keep_segments`。
- low-risk rule 若按统一阈值已进入 auto-apply（包括 `catchphrase_phrase`），就必须同步进入 manual editor 的 frontend-managed auto cut 共享集合，不能再出现“上游自动应用、下游不认”的分叉。
- manual-editor/apply 在 `subtitle_only` / `no_material_change` 路径不得再隐式重跑 multimodal trim review；应优先复用匹配的 review artifact。
- manual-editor/apply 在 `subtitle_only` / `no_material_change` 路径不得再隐式重解 packaging plan，也不得再调用 insert/music 规划；应优先复用旧 render plan 的包装参数。
- manual-editor/apply 在 `subtitle_only` / `no_material_change` 路径不得再隐式重跑 `infer_timeline_analysis(...)` 或 `build_smart_editing_accents(...)`；effect 输入应优先复用旧 render plan。
- render 入口在 manual `subtitle_only` 路径构造 AI 特效版时，不得再隐式重建 `section_choreography` 或重绑 `insert / music / subtitles`；应优先复用既有 render plan 绑定结果。
- render 入口在 manual `subtitle_only` 路径构造 AI 特效版时，不得再隐式重选 transition boundary，也不得再新建 emphasis / pulse / sound effect 事件；应优先复用既有 `editing_accents` 事件结构。
- render 执行层在 manual `subtitle_only` 路径不得再根据当前字幕隐式合成新的 overlay / video-transform accent 事件；应优先复用既有 `editing_accents`。
- render 主链中 packaged / ai_effect 若共享同一份 packaged/avatar 基线，不得再分别重复调用 packaged variant 解析；应先解析一次，再做分支级复制。
- packaged timeline 的 intro/insert 偏移 context 不得再在 subtitle mapping 与 accent mapping 中重复 probe/重复解析；应先解析一次 shared context，再按各自事件长度补算局部位移。
- packaged / ai_effect 若共享同一份 `outro.path`，trailing-gap allowance 不得再分别重复 probe 同一路径；应优先复用同一 `outro` 时长。
- 同一轮 render 中，同一输出文件的 media meta 不得再以“先取 duration、后取 full meta”为理由重复 probe；应优先复用第一次 probe 结果。
- avatar reusable / PIP / segmented-PIP 分支若前面已经拿到同一 `tmp_avatar_mp4` 的 probe 结果，后续 variant metadata 阶段不得再对同一文件重复 probe。
- cover 导出若最终只允许从 plain render 抽帧，不得再额外复制 `tmp_plain_mp4` 到 cover 专用副本，也不得继续保留未使用的 packaged 参数。
- cover seek helper 若最终只依赖 `job_id -> media_meta`，不得继续保留无效的 `tmpdir` 等历史上下文参数。
- manual editor synthetic timeline 的 `manual_editor_keep/manual_editor_removed` 不得再在业务文件私写 reason 集；应走共享 helper。
- packaged/avatar shared variant helper 若最终共享同一份字幕事实，不得继续保留 `original_subtitle_items/variant_subtitle_items` 这类伪双轨签名；应收口为单一 `subtitle_items` 输入。
- avatar variant 若真实事实已收缩为单一 `duration`，不得再额外缓存镜像 `editorial_timeline` 状态；需要 full-length keep segments 时应按 `duration` 现算。
- avatar variant 若没有独立 overlay event 事实层，不得继续保留只声明不生效的 `overlay_accents` 中间状态。
- packaged/plain shared variant helper 若 plain 路径真实只依赖 `duration` 生成 full-length keep timeline，不得继续保留整块 `original_editorial_timeline` 结构输入。
- plain path 若 helper contract 已直接消费 `duration`，调用层不得继续残留仅为兼容旧签名存在的 `plain_variant_editorial_timeline` 中间变量。
- ai_effect variant 若与 packaged variant 共享同一条 timeline 事实层，不得继续保留 `copy.deepcopy(packaged_editorial_timeline)` 这类镜像状态。
- ai_effect variant 若与 packaged variant 共享同一 source/subtitle 事实层，不得继续保留 `ai_effect_source_path`、`ai_effect_subtitles` 这类同值别名。
- ai_effect variant 若与当前 avatar commentary 共享同一事实层，不得继续保留 `copy.deepcopy(avatar_plan)` 这类只读消费下的镜像副本。
- avatar variant 若 `segments` 只由 `duration` 现算且只有一个消费点，不得继续保留 `avatar_variant_segments` 这类一次性中间别名。
- packaged / ai_effect 的 trailing-gap allowance 若只是各自 sync 校验前的一次性派生值，不得继续保留 `*_trailing_allowance` 这类局部别名。
- cover 导出路径若 `_get_cover_seek(...)` / `_select_cover_source_video(...)` 的结果只在 `extract_cover_frame(...)` 调用处消费一次，不得继续保留单独局部别名。
- packaged / ai_effect 的 outro path 若只为一次相等判断服务，不得继续保留 `*_outro_path` 这类一次性比较别名。
- ai_effect outro duration 若只为一次 `packaging_allowance_sec` 计算服务，不得继续保留 `ai_effect_outro_duration` 这类一次性局部值。
- sync 阻断集合若只为紧接着的一次 `if` 判断与报错拼接服务，不得继续保留独立 `blocking_sync_issues` 赋值层。
- avatar 输出是否就绪若已成为共享运行时事实，不得继续在 copy / srt / sync / artifact / bundle 多处手写同一组 guard；应收口为单一 `avatar_outputs_ready` 状态。
- avatar / cover 输出序列化若在 `local_paths` 与 `render_outputs` artifact 间共享，不得继续重复拼装相同字符串结果；应收口为共享序列化值。
- plain / packaged / ai_effect 核心输出路径若在 `local_paths`、`render_outputs` artifact、terminal return 间共享，不得继续重复做 `str(...)` 编码；应收口为共享序列化值。
- `render_outputs` 的稳定字段若在 `local_paths` 与 artifact payload 间共享，不得继续并排维护同一组 key；应收口为共享 `render_outputs` payload。
- render variant 的 subtitle sync / quality check 若同时服务 sync 阻断、variant bundle、artifact 报告，不得继续以多组平行局部值散着传；应先收口为共享 sync 映射与共享 quality-check payload。
- variant bundle 的 packaged `quality_checks` 若当前真实 contract 已是“直写 subtitle sync 字典”，消费端不得继续只认历史 `quality_checks["subtitle_sync"]` 嵌套 shape；应先对齐当前事实层，再保留旧 shape 兼容。
- scorecard 若只是在 `render_outputs` 上给四个 variant 做同构评分，不得继续在主流程手写四组 `media path + quality-check key` 平行映射；应收口为共享 variant spec helper。
- render summary 的报告规范化若已经有共享 normalize helper，下游 audit pack 不得继续复制 avatar reason category 推断；应先把 reason 分类收回共享 helper。
- batch render diagnostics 的 avatar 报告若既在构造阶段又在 reporting normalize 阶段消费，不得继续各自保留一份 `reason_category` 推断和字段裁剪逻辑；应收口为共享 avatar summary helper。
- cover render summary 若同时服务 batch render diagnostics 与 audit snapshot，不得继续在两侧各自手写相同字段裁剪；应收口为共享 cover summary helper。
- batch render diagnostics 的 `render_step` 若既在构造阶段又在 reporting normalize 阶段参与失败分类与 `issue_codes` 补全，不得继续保留两份同构解释逻辑；应收口为共享 render-step summary helper。
- manual-editor apply 的 `change_scope / render_strategy / *_changed / rerun issue code / return detail` 若本质同属一份变更合同，不得继续在 editorial、render_plan、rerun、API return 四处平行翻译；应收口为共享 manual-editor change contract。
- manual-editor `subtitle_only` 若已在 apply 端定义成共享 render contract，下游 render 入口不得继续本地用字符串拼条件重解释；应直接复用共享 manual-editor contract helper。
- variant 主路径若在 `local_paths["variants"]`、主输出别名、`render_output.output_path`、terminal return 间共享，不得继续散着取字段；应收口为共享 `serialized_variant_paths`。
- `packaged` 主输出路径/字幕若在 `local_paths["mp4"/"srt"]`、数据库输出字段、terminal return 间共享，不得继续多处各自取值；应收口为单一 primary output 事实。
- `render_outputs_payload` 中的 `packaged_mp4 / packaged_srt` 若本质就是主输出事实，不得继续与 `primary_output_*` 并排编码；应直接锚到同一主输出值。

## 阶段边界

### 阶段 A：框架改造完成

- 包范围：
  - `C1` 文本表面主链收口
  - `C2` Manual Editor 不变量收口
  - `C4` Render 运行时阻塞与回退收口
- 退出条件：
  - 主链输入/输出边界稳定，隐藏串写和事实层污染停止扩散。
  - manual-editor、render、review 不再因共享 contract 漂移而出现系统性错乱。
  - `run_render` 与 batch runner 的失败/降级原因可回放。

### 阶段 B：自动剪辑主链收口

- 包范围：
  - `C1` + `C2` + `C3` + `C4` + `C5`
- 退出条件：
  - 自动剪辑主链可批量稳定运行。
  - 规则候选生成、自动应用、人工阻断三者可审计、可解释、可门禁。
  - golden set、评分卡、阻断阈值能给出版本级前后对比。

### 阶段 C：质量增强完成

- 包范围：
  - `C1` + `C2` + `C3` + `C4` + `C5` + `C6`
- 退出条件：
  - 在不破坏前两阶段合同的前提下，明显降低误删、漏删和重复人工修正。
  - 自动粗剪质量提升来自可复现的评测结果，而不是个例观感。

## 本轮总目标

- 总目标：
  - 完成 `阶段 A -> 阶段 B -> 阶段 C` 的依赖式收口，最终形成“主链稳定、规则统一、运行时可回放、评测可门禁、质量可持续增强”的自动剪辑系统。
- 成功口径：
  - `C1-C6` 均有明确边界、当前状态、剩余缺口、验收证据与阻断条件。
  - 后续 agent 可只依赖本文件与 `docs/agent-current-state.md` 继续执行，不需要回放长对话历史。

## 当前判断

- 主体框架状态：`C1-C5 当前范围已收口`
- 主链收口状态：`阶段 B 主链已收口，剩余仅可选 breadth`
- 当前阶段：`主框架不再继续扩张；仅保留真实样本证据补充与 C6 延后质量增强`

## 收口包总览

| 包 | 名称 | 当前状态 | 预估收益 | 通过标准 |
|---|---|---|---|---|
| `C1` | 文本表面主链收口 | `当前范围可收口` | `+1~2` | 三层 surface 消费者主链无混用 |
| `C2` | Manual Editor 不变量收口 | `当前范围可收口` | `+1~2` | subtitle-only / auto cuts / keep segments 全链一致 |
| `C3` | 规则注册表与风险门禁统一 | `当前范围可收口` | `+1~2` | 候选生成、展示、自动应用计数一致 |
| `C4` | Render 运行时阻塞与回退收口 | `当前范围可收口` | `+1~2` | timeout / degraded / failed 原因可复核且不残留挂起 |
| `C5` | 真实任务评测与发布门禁 | `当前范围可收口` | `+1~2` | golden set + scorecard + regression gate 可常态化运行 |
| `C6` | 智能删减质量增强 | `延后` | `+5~8` | 废片识别与高风险复核显著降低误删 |

## C1 文本表面主链收口

- 目标：
  - 将 `raw / canonical / display` 从“已有抽象”推进到“主链无剩余歧义读取”。
- 当前已完成：
  - `subtitle_surfaces.py` 已建立三层 surface helper。
  - `manual-editor`、`render`、`projection validation`、部分 quality/review 路径已迁移。
  - `platform_copy`、`content_understanding_evidence`、`telegram_bot` 的共享读取入口已切到统一 surface contract，并有 display/canonical 专项回归保护。
  - `content_profile`、`intelligent_copy`、`domain_glossaries` 的 transcript/identity/domain 共享语义入口已切到 canonical surface，避免 display 抑制和 raw 噪声反灌内容理解与智能文案输入。
  - `content_profile` 的 subtitle polish source 已明确收回 display surface，避免字幕润色阶段再次回退到 canonical/raw 造成展示层合同漂移。
  - `subtitle_translation`、claim-evidence transcript、Telegram preview report 的字幕读取已回到统一 contract：翻译/claim grounding 读 canonical，人工复核 preview 读 display。
  - `subtitle_quality` 的归一化适配层已补透传 suppression metadata，display-suppressed 行不会在质量报告阶段被二次复活。
  - `manual-editor` source-row 的 `timing_text` 默认 authority 已收回 canonical/raw，不再让 display surface 反向控制分句与时序文本。
  - `speech/subtitle_pipeline.py` 的 canonical transcript fact layer 已收回 canonical helper，不再让 display surface 反向污染 canonical transcript。
  - `subtitle_consistency.py` 已显式收回 display surface，suppressed 行不会再经 consistency gate 被重新拼回可见字幕文本。
  - `subtitle_memory.py` 已把 recent subtitle 的 term/example/entity 上下文读取收回 canonical fact layer，不再优先读 `text_final` 反向污染 hotword / glossary / memory 输入。
  - `subtitle_surfaces.py` 现已区分“宽松 fallback helper”和“strict explicit-layer helper”；`pipeline/steps.py::_manual_editor_subtitle_items_from_editorial(...)` 已切到 strict helper，editorial subtitle projection 的 `text_final` 不会再自动回填成 `text_norm`。
  - `pipeline/steps.py::_load_source_subtitle_payloads_for_projection_validation(...)` 已不再把 canonical transcript 的 `text_canonical` 预先写成 `text_final`；source subtitles 进入 projection validation 前保持 fact-first，不在这里提前 display 化。
  - 同一 canonical segment 路径下，`text_raw/text_norm` 现在也不再通过 `segment["text"]` 这个兼容别名参与事实层回退；显式 raw/canonical 字段重新成为唯一优先来源。
  - `speech/subtitle_pipeline.py::_build_projection_entries_from_transcript_words(...)` 已不再把 transcript-word projection 的 `text_raw` 直接预写成 `text_final`；transcript-first projection entry 现在保持 `text_final=None`，display 层只在后续明确生成。
  - `pipeline/steps.py::_persist_projection_layer_to_subtitle_items(...)` 已不再在落库 `SubtitleItem` 时用 `text_final` 回补 `text_raw/text_norm`；projection refresh 持久化现在按 `raw -> canonical -> display` 顺序生成，不再把前面收口的 fact-first entry 在最后一步重新揉平。
- 仍需完成：
  - 主链结构已收口；仅保留可选真实样本 breadth，以防未来锚点暴露新的长尾 consumer。
  - 若后续出现新的 surface 漏口，应先按共享 helper / 显式层字段合同复验，而不是恢复大范围 surface 清理。
- 验收：
  - 规则匹配只读 `raw/canonical` 目标层。
  - 内容理解只读约定 surface。
  - 字幕显示只读 `display`。
  - 不再出现 display-suppressed 行被事实层读取复活。

## C2 Manual Editor 不变量收口

- 目标：
  - 保证 manual editor 是“复核与微调层”，不是第二条隐式自动链。
- 当前已完成：
  - `manual-editor/apply` 已避免默认字幕串写。
  - frontend-managed auto cuts 已回灌到 render keep segments。
  - `manual_editor_apply_semantics` 已接入 golden 主报告与 required checks：`run_auto_edit_recovery_golden_set.py` 现会对 reference job 计算 `session_baseline_matches_restored / roundtrip_matches_editorial / change_scope / timeline_changed / render_strategy`，并把结果写入 `case_rows`、`golden_set_summary.md` 与 `batch_report.json`。
  - `verify_manual_editor_apply_semantics.py` 已改为复用同一 shared helper；当前已有 4 条锚点纳入门禁：`noc_mt34_manual_editor_anchor`、`edc17_manual_editor_anchor`、`noc_mt34_short_done`、`noc_mt34_long_done`。
- 仍需完成：
  - 主链结构已收口；仅保留可选 broader evidence，例如 `base_keep_segments` 在更多真实 editorial/render-plan 形态下的补样。
  - 若后续再改 session/apply/render 任一段，优先复跑当前显式 `manual_editor_apply_semantics` 锚点，而不是扩题材面。
- 验收：
  - 纯字幕修改不会误判为 timeline 大改。
  - 已接受 auto cuts 不会被保存动作冲掉。
  - manual editor 保存后的 render 输入与 editorial 决策可对账。

## C3 规则注册表与风险门禁统一

- 目标：
  - filler、catchphrase、pause、repeated speech、smart delete 统一进入同一套规则注册表、候选协议、风险等级和自动应用门禁。
- 当前已完成：
  - 部分 smart cut candidate provenance 已打通。
  - repeated speech 旧候选回灌问题已修一轮。
  - 已新增共享规则注册表，统一维护 `reason -> kind / risk_level / match_surface_layer / label`；`smart_cut_candidates` 与 manual-editor 展示层不再各自复制一套映射。
  - 旧链 `repeated_speech` 候选已接入统一元数据归一化：即使仍来自 `manual_editor_full_transcript`，进入 `cut_analysis` 后也会稳定补齐 `source_text / match_surface / risk_level / rule_id`，不再是“只有部分规则有协议字段”的半成品。
  - `manual_editor` 的 frontend-managed auto cuts 与 `source_timeline_contract` 的 speech/pause reason 集合也已回收到共享注册表，`api/jobs.py` 和 `timeline_contract.py` 不再维护各自私有原因名单。
  - 共享 reason 集合现在进一步由 `RuleDefinition` 元数据推导，而不再是注册表内部的四份平行手写 `frozenset`；新增 `pause / smart_delete / repeated_speech` reason 时，只需更新规则定义本身，`manual_editor` 与 `timeline_contract` 的共享集合会自动同步。
- 仍需完成：
  - 仅在真实误删/误分流样本再次出现时，才继续细化 filler/catchphrase 子类与阈值。
  - 当前阶段不再为“体系完整”主动扩规则维度；优先保持共享合同单点生效。
- 验收：
  - 规则卡片计数、高亮计数、候选计数一致。
  - 切换任一规则只影响该规则。
  - 自动模式默认保守，误删率下降。

## C4 Render 运行时阻塞与回退收口

- 目标：
  - 让 `run_render` 从“能超时保护”推进到“真实阻塞源可分类、可降级、可审计、可回放”。
- 当前已完成：
  - batch runner 已支持 step timeout 与 `process` 级回收。
  - `avatar_full_track` 已具备 typed failure 分类。
  - `batch_report` / batch markdown / audit pack 已补透 `avatar_result.reason/detail/retryable/error_metadata`，render typed failure 不再在报告链里丢失。
  - 非 avatar 的 render 失败现在也有稳定归类：`render_variant_sync_blocked`、常见 `ffmpeg` 渲染/包装失败、`ffprobe` 失败会在 `render_diagnostics.render_step.reason` 中统一暴露；封面导出则通过 `cover_result` 记录 `done/degraded` 与 `cover_export_failed`。
  - fresh 真实 smoke 已验证 non-avatar render 的 `cover_result` 进入 `render_outputs -> batch_report -> audit_pack`，且 `render_step.status=done` 时不再误报 `render_failed`。
  - `edit_plan` 的音频派生文件自动重建现在也进入显式 runtime contract：当 clone/fresh replay 中 `audio_wav` storage_path 失效、`edit_plan` 退回从源视频重提音频时，`batch_report.json/md` 的 `live_stage_validations` 会显式记为 `edit_plan=warn`，并带 `issue_codes=["audio_artifact_rebuilt"]`，不再只是日志与 step metadata 中的隐藏 fallback。
  - render runtime 诊断现在不再完全依赖最终 `render_outputs` 才能进入报告链：`run_render` 已新增 `render_runtime_diagnostics` 中途 artifact，avatar/cover 的降级事实会在运行时即时落库；当最终 render 超时失败时，`batch_report.render_diagnostics` 仍能回放更早发生的 `avatar_full_track_call_timeout`，而不会再被较弱的 `missing_avatar_render` 覆盖。
  - `detailed_output_scorecard.avatar` 现在也已消费 `render_diagnostics.avatar_result`，长样本 timeout 场景不再误报“缺少 avatar_result”，而会显式标注 `avatar_full_track_call_timeout`。
  - `render_diagnostics_summary`、`golden_set_summary` 与 `live_readiness.render_end_state_stability` 现在都已聚合 root-cause 级 reason-count：不仅知道有几条 render failed / avatar degraded，还能直接看出主因是 `render_timeout_process`、`render_timeout_thread`、`render_failed`、`cover_export_failed` 还是 `avatar_full_track_call_timeout`；旧版 batch_report 在缺少该字段时也会从 jobs fallback 自动补齐。
  - fresh 长样本 render timeout 现在也已完成 strategy-aware 归类：`_classify_render_failure_reason(...)` 会结合 `sync_runner_timeout_strategy` 把超时区分为 `render_timeout_process` / `render_timeout_thread` / `render_timeout`，而不再把所有超时都压扁成泛化 `render_failed`。
- 仍需完成：
  - 仅保留可选真实样本 breadth：后续若自然出现新的 FFmpeg/provider 失败，再补 replay 证据。
  - 只有当新失败类别无法被现有 shared helper 表达时，才允许再扩 typed reason。
- 验收：
  - `render` 超时后不残留挂起任务。
  - `render` degraded 原因可稳定分类。
  - 报告层可直接看出是 `slot_timeout`、`call_timeout`、`busy_exhausted`、`provider_error` 还是 FFmpeg 失败。

## C5 真实任务评测与发布门禁

- 目标：
  - 让“感觉变好了”变成“有证据地提升了多少分”。
- 当前已完成：
  - 已有 golden slice、batch report、detailed scorecard、audit pack。
  - `required_checks` 已进入统一汇总，`manual_editor_apply_semantics` 已能作为合同项写入 golden 主报告。
  - `live_readiness` 现已直接消费 `manual_editor_apply_semantics_summary` 与 `render_diagnostics_summary`：
    - `manual_editor_apply_semantics_contract` 失败会直接阻断 gate；
    - `render_end_state_stability` 会对 `render_step.status=failed` 做终态阻断；
    - `cover_result / avatar_result` 的 degraded 会沉淀为 warning，而不再只埋在单 job 明细。
  - `blocking_quality_issues` 已接入 gate：`missing_subtitles`、`*_blocking`、`subtitle_semantic_contamination` 等稳定硬阻断码会直接阻断，不再依赖平均质量分间接体现。
  - “误删风险未消化”已开始前推到共享质量评估层：当 `high_risk_cuts` 仍未被 `LLM / multimodal / refine manual confirm` 收口时，会直接产出 `editing_high_risk_cuts_blocking`，并被现有 `blocking_quality_issues` gate 阻断。
  - `detailed_output_scorecard` 已新增批次级 `Aggregate Risk Metrics`，能稳定汇总 `high_risk_cut_count / manual_confirm_count / multimodal_pending_count / llm_reviewed_job_count / blocking_high_risk_job_count`，为真实任务前后对比和阈值化提供统一出口。
  - 已有 fresh 真实 smoke 证据证明新字段链不是停留在测试：
    - `heygem_anchor_b_done` 的 fresh render smoke 已真实产出 `batch_report.json + detailed_output_scorecard.json/md + golden_set_summary.md`，并确认 `blocking_quality_issues / manual_editor_apply_semantics_contract / render_end_state_stability` 进入 live gate，`Aggregate Risk Metrics` 进入 scorecard。
    - `noc_mt34_short_done` 的 fresh edit-plan smoke 也已真实产出同套报告链，并确认 `Aggregate Risk Metrics` 在真实产物中稳定出现。
  - `detailed_output_scorecard` 的 legacy fallback 口径已收口：当 partial/edit-plan fresh replay 缺失 `variant_timeline_bundle` 时，`editing_risk_metrics` 不再硬编码归零，而会从 `editorial.analysis + cut_analysis` 恢复 `llm_reviewed / manual_confirm_count / multimodal_pending_count / high_risk_cut_count`，避免同一份 scorecard 内出现 `editing=llm_cut_review=yes` 但 `editing_risk_metrics.llm_reviewed=false` 的自相矛盾。
  - golden manifest 已新增结构化 `risk_hints` contract，`run_auto_edit_recovery_golden_set.py` 会把每个 case 的历史高风险提示透传到 `case_rows / golden_set_summary.md`；后续 fresh replay 选择高风险锚点不再只能靠 `tags/notes` 和对话记忆。
  - 第一条按 `risk_hints` 驱动的 fresh 样本 `noc_mt34_long_done` 已完成：虽然 manifest 已标注 `reference_high_risk_cut_count=3`，但 `stop-after edit_plan` 的 fresh replay 仍只复现 `manual_confirm_count=7 / llm_reviewed=true`，没有复现 `high_risk_cut_count>0`。这说明后续 `C5` 不能再把“历史 reference 高风险”直接等同于“fresh gate 可复现高风险”，必须继续区分 stop-after 边界和 artifact 来源。
  - `detailed_output_scorecard` 现在进一步把风险指标来源显式化：`editing_risk_metrics.source` 会区分
    - `variant_timeline_bundle`
    - `legacy_editorial_cut_analysis`
    同时 aggregate 层新增 `variant_bundle_job_count / legacy_risk_job_count`。这已经用 `noc_mt34_short_done` 的 fresh replay 证实：当前 `manual_confirm=7 / multimodal_pending=4 / llm_reviewed=true` 仍只来自 legacy fallback，而不是 bundle 级高风险收口。
  - `editing_risk_metrics` 现在还会显式写出 `source_reason`，已区分：
    - `pre_render_stop_without_variant_bundle`
    - `render_failed_before_variant_bundle`
    - `variant_bundle_unavailable`
    这样 `noc_mt34_short_done` 这类 `stop-after edit_plan` 样本已经能明确标注成“pre-render 阶段天然无 bundle”，而不是继续和真正的 bundle 缺失异常混在一起。
  - `run_edit_plan` 现在已经前移写入 diagnostics-only `variant_timeline_bundle`，所以 `stop-after edit_plan` 的 fresh scorecard 不再需要用 `legacy_editorial_cut_analysis` 恢复编辑风险摘要；render 阶段只负责补全媒体 variants 并覆盖成完整 bundle。
  - golden manifest 的 `risk_hints` 现在已补入阶段语义：不仅能记录 `reference_high_risk_cut_count`，还能显式区分 `reference_expected_stage / reference_expected_source / fresh_expectations.<stage>`，避免再把 render 后的历史高风险误判成 edit-plan fresh 必现值。
  - golden 报告链现已新增 `risk_alignment` / `risk_alignment_summary`，会把 `reference_high_risk_cut_count` 与 fresh `editing_risk_metrics` 对账后显式输出：
    - 是否真的复现高风险 cut
    - fresh 风险信号来自 `variant_timeline_bundle` 还是 legacy fallback
    - 当前 mismatch 属于“高风险未复现”还是“事实源错位”
  - golden 报告链现在还会自动采集 `reference_risk_snapshot`，直接把 reference job 的真实风险画像并入 batch/golden 产物，而不再需要额外查数据库：
    - reference 是否存在 `variant_timeline_bundle / render_outputs / cut_analysis`
    - reference `high_risk_cut_count`
    - reference `llm_reviewed / llm_candidate_count / llm_error`
    - reference `manual_confirm_candidate_count / multimodal_pending_count`
    - `first_high_risk_cut_reason`
  - 对当前 manifest 与工作区 reference jobs 的扫描已确认：目前只有 `noc_mt34_short_done` 与 `noc_mt34_long_done` 两条 reference job 真正带非零 `variant_timeline_bundle.high_risk_cuts`；其余样本并没有完整 bundle/render 级高风险证据。
  - 但这不代表其余样本没有可用的风险锚点：全库扫描已确认还存在一类 `edit_plan` 风险锚点，虽然没有 `high_risk_cuts`，但 `cut_analysis/refine_decision_plan` 带极高 `manual_confirm_candidate_count`。这类样本现在也已开始进入 manifest：
    - `edc17_manual_editor_anchor`：reference `manual_confirm_candidate_count=94`
    - `noc_mt34_s06mini_edit_plan_risk_anchor`：reference `manual_confirm_candidate_count=131`
  - 两条样本的 fresh render smoke 都已补完，但都没有复现非零高风险：
    - `noc_mt34_short_done` fresh render：`high_risk_cut_count=0`，同时暴露 `subtitle_sync_issue`
    - `noc_mt34_long_done` fresh render：`high_risk_cut_count=0`，同时 render 在 `300s` timeout 失败，运行日志另有 `avatar_full_track_call_timeout` 降级事实
  - `noc_mt34_short_done` 的 fresh `stop-after edit_plan` 现已用新 contract 复验：
    - 产物目录：`output/test/auto-edit-recovery-golden/c5-risk-alignment-rerun-short/20260611-104538`
    - `golden_set_summary.md` 已显式写出：
      - `reference_high_risk_case_count: 1`
      - `reproduced_case_count: 0`
      - `mismatch_codes: reference_high_risk_not_reproduced=1`
    - 同一 case 的 `risk_alignment` 已显示：
      - `fresh_source=variant_timeline_bundle`
      - `fresh_high_risk_cut_count=0`
      - `fresh_manual_confirm_count=7`
      - `fresh_multimodal_pending_count=4`
      - `fresh_llm_reviewed=true`
      - `status=mismatch`
  - 同一条样本又补了一轮带 `reference_risk_snapshot` 的 fresh 复验：
    - 产物目录：`output/test/auto-edit-recovery-golden/c5-reference-risk-snapshot-rerun-short/20260611-105848`
    - `golden_set_summary.md` / `batch_report.json` 中已显式出现：
      - `reference_risk_snapshot.artifact_types = render_outputs, variant_timeline_bundle`
      - `reference_risk_snapshot.high_risk_cut_count = 1`
      - `reference_risk_snapshot.llm_reviewed = false`
      - `reference_risk_snapshot.llm_error = llm_cut_review_failed`
      - `reference_risk_snapshot.first_high_risk_cut_reason = silence`
    - 因此当前 `noc_mt34_short_done` 的 reference/fresh 错位已经可以直接在同一份报告里看清：
      - reference：`high_risk_cut_count=1 / llm_reviewed=false`
      - fresh：`high_risk_cut_count=0 / manual_confirm_count=7 / multimodal_pending_count=4 / llm_reviewed=true`
  - 新增 `edit_plan` 风险锚点 `noc_mt34_s06mini_edit_plan_risk_anchor` 已完成 fresh 复验：
    - 产物目录：`output/test/auto-edit-recovery-golden/c5-s06mini-risk-anchor-rerun-fixed/20260611-110725`
    - 已确认：
      - fresh `detailed_output_scorecard.json` 中：
        - `manual_confirm_count=96`
        - `multimodal_pending_count=1`
        - `llm_reviewed=true`
      - 同一份 `golden_set_summary.md / batch_report.json` 中：
        - `reference_risk_snapshot.manual_confirm_candidate_count=131`
        - `reference_risk_snapshot.refine_candidate_manual_confirm=131`
        - `risk_alignment.fresh_manual_confirm_count=96`
        - `risk_alignment.fresh_multimodal_pending_count=1`
        - `risk_alignment.mismatch_codes=fresh_source_mismatch`
    - 这说明 `C5` 现在不再只有“高风险 cut 未复现”的 render 后反例，也有了一条“reference 是 edit-plan 高 manual-confirm 风险，fresh 仍保持高 manual-confirm / multimodal pending”的活锚点。
  - `manual_confirm_heavy` 阻断门禁现已真正接入 live gate，而不再只停留在报表数字：
    - `src/roughcut/pipeline/quality.py` 已新增 `editing_manual_confirm_heavy_blocking`，当前阈值为 `candidate_manual_confirm >= 50`
    - `scripts/build_batch_output_scorecard.py` 已同步新增
      - job 级 `editing_risk_metrics.blocking_manual_confirm_heavy`
      - aggregate 级 `blocking_manual_confirm_job_count`
    - 定向验证：
      - `python -m py_compile src/roughcut/pipeline/quality.py scripts/build_batch_output_scorecard.py tests/test_quality_profile_soft_gate.py tests/test_build_batch_output_scorecard.py`
      - `$env:PYTHONPATH='src'; python -m pytest tests/test_build_batch_output_scorecard.py -k "editing_risk_metrics or render_markdown_includes_aggregate_and_job_level_editing_risk_metrics" -q`（`4` 项通过）
      - `$env:PYTHONPATH='src'; python -m pytest tests/test_quality_profile_soft_gate.py -k "high_risk_cuts_blocking or manual_confirm_heavy_edit_plan_as_blocking or multimodal_trim_review_timeout or refine_decision_summary_signal" -q`（`3` 项通过）
    - fresh 真实复验：
      - 产物目录：`output/test/auto-edit-recovery-golden/c5-s06mini-manual-confirm-gate-rerun/20260611-111738`
      - `batch_report.json` 中已确认：
        - `quality_issue_codes` 同时出现 `editing_high_risk_cuts_blocking` 与 `editing_manual_confirm_heavy_blocking`
        - `live_readiness.checks.blocking_quality_issues.issue_code_counts.editing_manual_confirm_heavy_blocking = 1`
      - `detailed_output_scorecard.json` 中已确认：
        - `editing_risk_metrics.high_risk_cut_count = 1`
        - `editing_risk_metrics.manual_confirm_count = 97`
        - `editing_risk_metrics.blocking_high_risk_cuts = true`
        - `editing_risk_metrics.blocking_manual_confirm_heavy = true`
        - `aggregate_risk_metrics.blocking_manual_confirm_job_count = 1`
      - `golden_set_summary.md` 中已确认：
        - `reference_manual_confirm_candidate_count = 131`
        - `fresh_high_risk_cut_count = 1`
        - `fresh_manual_confirm_count = 97`
        - `high_risk_reproduced = True`
    - 这说明 `noc_mt34_s06mini_edit_plan_risk_anchor` 已从“高 manual-confirm 风险样本”升级成“fresh 可复现 high-risk + manual-confirm-heavy 双阻断活锚点”。
  - `required_checks` 现已从“全靠 fake stage 名比对”推进成 typed check contract，并在 `S06mini` 活锚点上完成一轮真实收口：
    - `scripts/run_auto_edit_recovery_golden_set.py` 已新增 evaluation-side typed check inspection：
      - `manual_editor_ready` 改为基于 `_build_manual_editor_readiness(...).can_open_editor`
      - `subtitle_projection` 改为直接消费 `canonical_projection_quality_* / missing_subtitles / subtitle_semantic_contamination`
      - `cut_analysis_traceability` 改为直接检查 evaluation job 的 `cut_analysis / variant_timeline_bundle`
    - `src/roughcut/edit/cut_analysis.py` 现已把 `accepted_cuts` 一并走 metadata normalization，且遗留 backend smart candidates 不再 silently drop
    - `src/roughcut/pipeline/steps.py` 现已把 `high_risk_cuts` 的 `source_text / match_surface / match_surface_layer / risk_level / rule_id` 透传进 diagnostics bundle
    - 定向验证：
      - `python -m py_compile scripts/run_auto_edit_recovery_golden_set.py src/roughcut/edit/cut_analysis.py src/roughcut/pipeline/steps.py tests/test_run_auto_edit_recovery_golden_set.py tests/test_manual_editor_helpers.py`
      - `$env:PYTHONPATH='src'; python -m pytest tests/test_run_auto_edit_recovery_golden_set.py -k "required_checks or traceable_cut_candidate or manual_editor_apply_semantics" -q`（`7` 项通过）
      - `$env:PYTHONPATH='src'; python -m pytest tests/test_manual_editor_helpers.py -k "build_cut_analysis_payload_backfills_silence_metadata_for_accepted_cuts or build_cut_analysis_payload_backfills_repeated_speech_metadata_from_legacy_candidate or build_cut_analysis_payload_preserves_smart_rule_candidate_metadata" -q`（`3` 项通过）
    - fresh 真实复验：
      - 首轮：`output/test/auto-edit-recovery-golden/c5-s06mini-required-checks-rerun/20260611-113038`
        - `required_check_statuses` 已把三项失败拆成真实原因：
          - `manual_editor_ready`: stop-after 终态污染
          - `subtitle_projection`: `canonical_projection_quality_warning`
          - `cut_analysis_traceability`: `missing_traceability_items=4`
      - 修正后：`output/test/auto-edit-recovery-golden/c5-s06mini-required-checks-rerun-v2/20260611-113507`
        - `required_checks_contract_passed = 2/3`
        - `manual_editor_ready = true`
    - `src/roughcut/api/jobs.py::_build_manual_editor_readiness(...)` 已补 stop-after partial replay 特例：
      - 若 job 只是按 `stop_after` 主动收尾、且 manual editor 所需工件已齐，`cancelled` 不再覆盖成 `readiness.status=failed`
      - 验证：`python -m pytest tests/test_manual_editor_readiness_progress.py -k "stop_after_cancelled_job_as_ready or ready_clears_current_step or failed_step_prefers_error_message or does_not_report_complete_when_outputs_are_missing" --basetemp '.tmp/pytest-manual-editor-readiness' -q`（`4` 项通过）
        - `cut_analysis_traceability = true`
        - 仅剩 `subtitle_projection` 未通过
- 仍需完成：
  - 主链门禁与报告合同已收口；只保留少量真实锚点用于回归，不再追求题材面铺开。
  - 仅当新的真实失败样本证明当前 scorecard / required_checks 仍有交付噪音时，再做一轮收缩。
  - 若无新的真实反证，不再新增报表字段或门禁种类。
- 验收：
  - 任意一轮主链修改后可用少量真实锚点复跑。
  - 关键指标回退时能自动阻断。
  - partial/edit-plan 的 fresh scorecard 能看清自动删减和人工确认规模即可。

## C6 智能删减质量增强

- 目标：
  - 在主链稳定后，再提高“像人剪过”的质量上限。
- 当前状态：
  - `延后`。阶段 B 主链已收口；只有当新的真实误删/漏删样本出现时，才做直接影响质量的轻量增强。
- 仍需完成：
  - 基于真实误删/漏删样本做小步规则或阈值调整。
  - 不新增大模型评审链、不新增复杂反馈系统。
- 验收：
  - 明显漏删废话减少。
  - 文本低信息但画面有价值的片段误删下降。
  - 同类素材上的人工重复修正减少。

## 建议执行顺序

1. `C1` 文本表面主链收口
2. `C2` Manual Editor 不变量收口
3. `C4` Render 运行时阻塞与回退收口
4. `C3` 规则注册表与风险门禁统一
5. `C5` 真实任务评测与发布门禁
6. `C6` 智能删减质量增强

## 每包完成后的预期效果

- `C1 + C2` 完成后：
  - 系统可达到“主链可解释、可人工复核、不再系统性乱改输入事实层”。
- `C3 + C4` 完成后：
  - 系统可达到“可批量跑、可稳定降级、自动删减行为基本可信”。
- `C5` 完成后：
  - 系统可达到“分数提升与回退都有证据，不再靠截图和主观感受评估”。
- `C6` 完成后：
  - 系统可从“可用自动初剪”进一步提升到“更接近高质量自动粗剪”。

## 版本收口口径

- `阶段 A：框架改造完成`
  - `C1 + C2 + C4` 完成
- `阶段 B：自动剪辑主链收口`
  - `C1 + C2 + C3 + C4 + C5` 完成
- `阶段 C：质量增强阶段完成`
  - `C1 + C2 + C3 + C4 + C5 + C6` 完成

当前状态应定义为：`阶段 B` 主链已收口；若继续推进，只应基于真实样本进入可选证据补充或 `阶段 C` 的轻量质量增强。
