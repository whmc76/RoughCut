# Correction Framework Refactor

**文档同步版本：** RoughCut v0.1.5（2026-04-27）

## Why

The old proofreading and verification path had four partially overlapping systems:

- `glossary_engine`: term replacement oriented
- `subtitle_memory`: alias-heavy subtitle correction heuristics
- `entity_graph` / `content_profile_memory`: review-confirmed entity memory
- `content_understanding_verify`: weak hybrid search with unstructured database hits

This produced three recurring failures:

- identity drift: `ARC -> AC/ASC`, `狐蝠工业 -> 鸿福`, `KissPod -> 战术笔`
- weak correction: glossary review often returned `0`, so obvious contradictions were not blocked
- shallow research: online search and internal memory were not merged into an explainable evidence chain

## Reference Patterns

This refactor borrows from three mature patterns:

- spaCy `EntityLinker`: knowledge base + candidate generation + context-based disambiguation  
  Source: <https://spacy.io/api/entitylinker>
- Microsoft Presidio recognizer registry: layered recognizers, context enhancement, allow-lists, and decision tracing  
  Source: <https://microsoft.github.io/presidio/analyzer/adding_recognizers/>
- Haystack hybrid retrieval: keyword retrieval + semantic retrieval + merge/rerank  
  Source: <https://docs.haystack.deepset.ai/docs/opensearchhybridretriever>

## Target Architecture

The stronger RoughCut correction stack should be entity-centric:

1. `Catalog Candidate Layer`
   - unify graph-confirmed entities, review-confirmed entities, builtin glossary aliases, and source evidence
   - output candidate entities with support score, confidence, alias hits, matched fragments, and origins

2. `Verification Bundle Layer`
   - pass structured entity candidates into content verification
   - keep online search and internal candidates separate, but ranked in one bundle

3. `Correction Decision Layer`
   - only allow brand/model overwrite when supported by at least two evidence routes
   - downgrade to `needs_review` on narrative conflict instead of silently guessing

4. `Feedback Writeback Layer`
   - manual review continues to update `entity_graph` and correction memory
   - verified aliases become reusable catalog evidence in later runs

## Implemented Foundation

This round implemented the foundation, not the full end-state:

- `content_understanding_retrieval.py`
  - added entity-centric retrieval and scoring
  - now merges:
    - `entity_graph`
    - `content_profile_memory.confirmed_entities`
    - builtin glossary aliases
  - returns candidate payloads with:
    - `brand`
    - `model`
    - `primary_subject`
    - `matched_queries`
    - `matched_evidence_texts`
    - `matched_aliases`
    - `matched_fields`
    - `source_origins`
    - `support_score`
    - `confidence`
    - `evidence_strength`

- `content_understanding_verify.py`
  - `HybridVerificationBundle` now includes `entity_catalog_candidates`
  - bundle construction accepts:
    - `subject_domain`
    - `evidence_texts`
    - `glossary_terms`
    - `confirmed_entities`
  - prompt now explicitly tells the verifier to use structured entity candidates as secondary evidence

- `content_profile.py`
  - both verification entrypoints now pass structured evidence texts and confirmed entities into bundle construction
  - identity rewrite guard was tightened to avoid inventing theme/summary when current clip lacks strong local support

- `content_profile_feedback.py`
  - review feedback snapshot now exposes entity catalog counts and candidates

## Current Gains

- verification is no longer limited to plain search queries and generic database hits
- glossary-only evidence can now generate provisional brand/model candidates even without graph hits
- entity candidates are explainable and testable instead of living only inside prompts
- independent clips remain protected from neighbor contamination; related-profile backfill still stays manual-merge only

## Next Steps

### P0

- add domain-aware alias conflict blocking:
  - bag/tool/food cross-category contamination
- require dual-route support before overwriting `subject_brand` or `subject_model`
- surface entity-candidate evidence into `quality.py` so identity contradictions block auto-pass

### P1

- build a dedicated `EntityCatalog` module instead of leaving candidate generation inside retrieval
- add stronger model-family handling:
  - `ARC / AC / ASC`
  - `F2 / S11 PRO`
  - `狐蝠工业 / 鸿福 / FOXBAT`

### P2

- create a fixed regression corpus from the EDC test folder
- measure:
  - missing brand rate
  - missing model rate
  - narrative conflict miss rate
  - continuous-clip precision

## Acceptance Signals

The refactor is moving in the right direction if:

- `brand_missing_among_done` drops materially
- `model_missing_among_done` drops materially
- obvious conflict cases stop escaping glossary review
- manual review decisions increasingly become reusable graph evidence instead of one-off fixes
