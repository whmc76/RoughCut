# Verification Framework Execution Checklist

## This round

- [x] 固化独立 `Entity Catalog`，覆盖当前高频 EDC 品牌、型号、别名和类目关键词
- [x] 将 `builtin_entity_catalog` 接入 `content_understanding_retrieval`
- [x] 让候选评分纳入 `supporting_keyword`
- [x] 增加 `entity_catalog_narrative_conflict`，阻断品牌/型号与叙事字段串线
- [x] 引入“型号族兼容”判断，避免 `FXX1` / `FXX1小副包` 这类同族型号互判冲突
- [x] 优化 verification backfill，优先吃 `builtin_entity_catalog` 候选并接受 alias/keyword 级本地证据
- [x] 优化 verification candidate 排序，优先选择与当前 `brand/model/domain` 对齐的候选
- [x] 允许在“当前品牌与当前型号天然冲突”时，用强候选纠正错误品牌
- [x] 将 `apply_identity_review_guard` 接入 enrichment 主链，而不是只停留在独立入口
- [x] 在 quality gate 侧同步接入“候选与当前型号对齐”的排序，压低 glossary 噪声候选
- [x] 补回归脚本 `--samples`，支持定点真样本复跑
- [x] 补单元测试和定点真实样本验证

## Validation snapshot

- 单测回归：`PYTHONPATH=src python -m pytest tests/test_content_profile.py tests/test_pipeline_quality.py tests/test_content_understanding_retrieval.py -q`
  - 结果：`163 passed`
- 步骤级回归：`PYTHONPATH=src python -m pytest tests/test_pipeline_steps.py -q -k "glossary_review or related_profile or injects_related_profile_source_context_for_adjacent_clip"`
  - 结果：`6 passed`
- 真样本定点复跑：
  - 报告：[edc_summary_regression_targeted_catalog_v6_20260410_170152.md](/E:/WorkSpace/RoughCut/output/test/edc_summary_regression_targeted_catalog_v6_20260410_170152.md)
  - 结构化结果：[edc_summary_regression_targeted_catalog_v6_20260410_170152.json](/E:/WorkSpace/RoughCut/output/test/edc_summary_regression_targeted_catalog_v6_20260410_170152.json)
  - `VID_20260112_123927.mp4` 已稳定到 `NEXTOOL / F2 / 多功能工具钳` 语境
  - `IMG_0025.MOV` 仍未自动纠正到正确品牌，但已从“静默通过的错误结果”收敛为 `needs_review`，不会再无提示放过

## Still open

- [ ] 将 `Entity Catalog` 从内建静态表升级为可回灌的持久库
- [ ] 让 `glossary_review` 在 gate 命中时执行更积极的品牌回填，而不是只标 `needs_review`
- [ ] 给多主体视频增加主产品优先级判定，降低 `F2 / S11 PRO` 混写
- [ ] 为大批量 regression 增加增量落盘和续跑能力
