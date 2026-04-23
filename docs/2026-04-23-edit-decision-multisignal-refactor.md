# Edit Decision Multisignal Refactor

## Goal

RoughCut should not treat silence as disposable by default. A silent region can be a meaningful product showcase, hands-on operation, detail appreciation, or transition beat. A spoken region can also be disposable when it is a clear interruption, false start, or retake marker.

The edit decision layer now uses a multisignal evidence model:

- VAD silence is only the first candidate source.
- Subtitle semantics protect normal language, parameters, comparison, and showcase cues.
- Transcript overlap protects speech that may not align cleanly with subtitle windows.
- Scene boundaries provide visual activity evidence for silent showcases.
- Section role and editing skill decide whether a gap belongs to detail/body B-roll or hook/CTA protection.
- Retake and interruption cues produce hard cut candidates when disposable.

## Reference Projects And Lessons

- `auto-editor`: useful baseline for audio/VAD-driven automatic removal, but RoughCut should not copy its silence-first assumption.
- `JumpCutter`: useful jump-cut reference, but it highlights the risk of deleting pauses that carry visual meaning.
- `PySceneDetect`: scene changes are a low-cost visual signal; they should increase showcase protection near silent gaps.
- `WhisperX`: word-level alignment and transcript evidence motivate keeping ASR/transcript overlap separate from rendered subtitle windows.

## Implementation Shape

`EditRangeEvidence` is the shared evidence payload for candidate ranges. It scores:

- `visual_showcase_score`
- `language_score`
- `retake_score`
- `protection_score`
- `removal_score`
- explanatory `tags`

`CutCandidate.to_dict()` now carries `evidence`. `EditDecision.analysis` includes `decision_methodology` and `cut_evidence_summary`. The LLM high-risk cut review receives this evidence instead of only raw timing and nearby subtitles.

## Follow-Up Hooks

- Add image-difference or optical-flow activity as another visual evidence source.
- Persist rejected/protected cut examples into creator memory.
- Surface evidence tags in the review UI for faster manual correction.
