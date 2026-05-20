# MOSS-Audio 8B ASR Docker Benchmark

Date: 2026-05-05

## Scope

Compare the current RoughCut Docker ASR service against MOSS-Audio 8B Instruct and 8B Thinking on the same three 30-second Chinese creator-video samples.

Current ASR:

- Service: `vibevoice-asr-codex`
- Endpoint: `http://127.0.0.1:6001/transcribe`
- Model reported by health endpoint: `Dubedo/VibeVoice-ASR-INT8`

MOSS-Audio:

- Docker compose: `docker-compose.moss-audio.yml`
- Endpoint shape: `/generate`, compatible with MOSS-Audio usage-guide request semantics.
- Models:
  - `OpenMOSS-Team/MOSS-Audio-8B-Instruct`
  - `OpenMOSS-Team/MOSS-Audio-8B-Thinking`

## Notes

Official SGLang startup exposed a model packaging mismatch: the MOSS-Audio 8B `preprocessor_config.json` references `processing_palomar_myaut_mel_whisper.PalomarProcessor`, while the model repo exposes `processing_moss_audio.MossAudioProcessor`. To keep the test moving with Docker deployment, the local MOSS service uses the official `MossAudioModel` and `MossAudioProcessor` loading path instead of SGLang `AutoProcessor`.

The first MOSS model start downloaded about 18GB of weights and loaded in about 535 seconds. Cached model reloads took about 92-95 seconds.

## Commands

Build MOSS image with the local CUDA/PyTorch base image already present on this machine:

```powershell
$env:MOSS_AUDIO_BASE_IMAGE='vibevoice-int8:local'
$env:MOSS_AUDIO_INSTALL_OS_DEPS='false'
docker compose --profile moss-audio-8b-instruct -f docker-compose.moss-audio.yml build moss-audio-8b-instruct
```

Run MOSS Instruct:

```powershell
docker compose --profile moss-audio-8b-instruct -f docker-compose.moss-audio.yml up -d --force-recreate moss-audio-8b-instruct
```

Run MOSS Thinking:

```powershell
docker compose --profile moss-audio-8b-thinking -f docker-compose.moss-audio.yml up -d --force-recreate moss-audio-8b-thinking
```

Benchmark command pattern:

```powershell
uv run python scripts\benchmark_http_asr_compare.py `
  --inputs "E:\WorkSpace\RoughCut\data\runtime\jobs\af3f56f7-1dc3-4b83-ad2f-c32be55edd59\20260212-141536 补充说明noc mt34开箱的快开自定义方式.mp4" `
           "E:\WorkSpace\RoughCut\data\runtime\jobs\7b4ca848-d4dc-41e0-bacf-800d1a5cbc8a\20260212-142025 以noc mt34为例 讲解展示了edc折刀的多种快开放式和简单的手法教学.mp4" `
           "E:\WorkSpace\RoughCut\data\runtime\jobs\fb30a42c-1af1-4c78-b065-bc3cd4004b2e\20260228-152013 奈特科尔 nitecore EDC17开箱以及和edc37的对比.mp4" `
  --sample-seconds 30 `
  --candidates current `
  --timeout-sec 1800 `
  --max-new-tokens 1024
```

## Results

| Candidate | Samples | Avg RTF | Avg text length | Keyword hit rate | Result JSON |
|---|---:|---:|---:|---:|---|
| `current_vibevoice_int8` | 3 | 0.570 | 118.0 | 0.136 | `output/test/asr-bench/results/http_compare_20260505_014047.json` |
| `moss_audio_8b_instruct` | 3 | 0.110 | 104.667 | 0.000 | `output/test/asr-bench/results/http_compare_20260505_021700.json` |
| `moss_audio_8b_thinking` | 3 | 0.097 | 103.333 | 0.000 | `output/test/asr-bench/results/http_compare_20260505_023054.json` |

No reference transcript was available, so CER was not computed. Keyword hit rate is a weak proxy derived from filename terms; use a hand-labeled manifest for a real CER/WER decision.

## Qualitative Findings

For these three domain samples, current VibeVoice INT8 preserved product terms better on the flashlight sample:

- Current: `edc37`, `奈特科尔`, `edc17`
- MOSS Instruct: `E D C三七`, `耐克尔`, `E C幺七`
- MOSS Thinking: `E D C三七`, `耐克尔`, `E C幺七`

MOSS output was cleaner in the sense that it omitted `[Silence]` markers and filler brackets, but it also truncated or compressed some sample endings. MOSS Instruct and Thinking were very close to each other on these short ASR-only prompts; Thinking did not show a measurable ASR advantage here.

## Current Recommendation

For RoughCut's current short-form Chinese product/unboxing ASR, keep `VibeVoice-ASR-INT8` as the default. MOSS-Audio 8B is faster on these 30-second samples after the model is loaded, but it is weaker on domain terms and alphanumeric product names without prompt or hotword adaptation.

Next useful test: build a labeled manifest with 5-10 representative clips and reference transcripts, then rerun with `--manifest-json` to get CER instead of relying on filename keyword hits.

## Hotword Ablation

After the first pass, we reran the same three samples to separate raw model behavior from hotword/prompt effects.

| Candidate / condition | Samples | Avg RTF | Avg text length | Keyword hit rate | Result JSON |
|---|---:|---:|---:|---:|---|
| `current_vibevoice_int8`, filename hotwords | 3 | 0.570 | 118.0 | 0.136 | `output/test/asr-bench/results/http_compare_20260505_014047.json` |
| `current_vibevoice_int8`, no hotwords | 3 | 0.569 | 117.667 | 0.000 | `output/test/asr-bench/results/http_compare_20260505_023655.json` |
| `moss_audio_8b_instruct`, no keyword prompt | 3 | 0.110 | 104.667 | 0.000 | `output/test/asr-bench/results/http_compare_20260505_021700.json` |
| `moss_audio_8b_instruct`, keyword prompt | 3 | 0.108 | 105.333 | 0.182 | `output/test/asr-bench/results/http_compare_20260505_023932.json` |
| `moss_audio_8b_thinking`, no keyword prompt | 3 | 0.097 | 103.333 | 0.000 | `output/test/asr-bench/results/http_compare_20260505_023054.json` |
| `moss_audio_8b_thinking`, keyword prompt | 3 | 0.109 | 102.0 | 0.045 | `output/test/asr-bench/results/http_compare_20260505_024218.json` |

The flashlight sample shows the difference most clearly:

- VibeVoice with filename hotwords: `edc37`, `奈特科尔`, `edc17`
- VibeVoice without hotwords: `ETC三七`, `耐克`, `EC17`
- MOSS Instruct without keyword prompt: `E D C三七`, `耐克尔`, `E C幺七`
- MOSS Instruct with keyword prompt: `EDC37`, `奈特科尔`, `EDC17`
- MOSS Thinking with keyword prompt: still split `E D C三七` and `E C幺七`, but kept `奈特科尔`

Updated conclusion: the first-pass VibeVoice advantage on domain terms came largely from RoughCut's filename/hotword path, not from raw ASR alone. MOSS-Audio 8B Instruct also benefits strongly from explicit keyword prompting and matched or exceeded the simple keyword-hit proxy when prompted. MOSS-Audio 8B Thinking did not help this ASR-only task in this small sample.

## Speed And Resource Usage

Resource sampling was run on the same three 30-second samples. Current VibeVoice used filename hotwords. MOSS Instruct and Thinking used the same keyword prompt condition as the hotword ablation. MOSS was run one model at a time. The existing VibeVoice service remained up during MOSS measurements, so MOSS GPU numbers below are whole-GPU totals rather than isolated per-container GPU memory.

| Candidate | Model ready time | Wall time for 3 samples | Avg infer / 30s sample | Avg RTF | Container CPU avg / peak | Container RAM avg / peak | Whole-GPU used avg / peak | GPU util avg / peak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `current_vibevoice_int8` | already running | 59.3s | 19.603s | 0.655 | 99.31% / 100.24% | 2.99 / 2.99 GiB | 16.5 / 16.6 GiB | 36.3% / 44.0% |
| `moss_audio_8b_instruct` + keywords | 95.1s cached reload | 10.7s | 3.400s | 0.113 | 175.47% / 307.93% | 1.47 / 1.59 GiB | 31.7 / 31.7 GiB | 65.8% / 78.0% |
| `moss_audio_8b_thinking` + keywords | 94.4s cached reload | 9.8s | 3.117s | 0.104 | 176.88% / 283.46% | 1.50 / 1.59 GiB | 31.6 / 31.6 GiB | 67.5% / 77.0% |

Raw measurement files:

- `output/test/asr-bench/results/http_compare_20260505_024544.json`
- `output/test/asr-bench/results/http_compare_20260505_024814.json`
- `output/test/asr-bench/results/http_compare_20260505_025046.json`
- `output/test/asr-bench/results/resource_current_vibevoice_20260505_0248.jsonl`
- `output/test/asr-bench/results/resource_moss_instruct_20260505_0248.jsonl`
- `output/test/asr-bench/results/resource_moss_thinking_20260505_0248.jsonl`

Operational takeaway:

- VibeVoice is much lighter to keep resident and leaves enough GPU headroom for the rest of RoughCut.
- MOSS 8B is about 5.8-6.3x faster per 30-second sample after loading, but it effectively monopolizes the 32GB GPU when VibeVoice is also resident.
- MOSS cached reload adds about 95 seconds before first request; first-ever start also downloads about 18GB of weights and took about 9 minutes in this run.
- MOSS is attractive as an on-demand batch ASR candidate, but not as a continuously resident sidecar on this single-GPU workstation unless other GPU services are stopped.

## Instruct Quantization Follow-Up

Thinking has been dropped from further optimization. This pass only tests `MOSS-Audio-8B-Instruct` with bitsandbytes runtime quantization. VibeVoice was stopped before this pass to remove its resident GPU memory from the MOSS measurements.

Isolation baseline:

- Before stopping VibeVoice: whole-GPU used `13369 MiB / 32607 MiB`
- After stopping VibeVoice: whole-GPU used `1893 MiB / 32607 MiB`

Docker additions:

- `moss-audio-8b-instruct-bnb8`: `--quantization bnb-8bit`, port `30082`
- `moss-audio-8b-instruct-bnb4`: `--quantization bnb-4bit`, port `30083`
- Service health now reports model quantization and PyTorch CUDA allocated/reserved memory.

| Candidate | Quantization | Load time | Health CUDA allocated / reserved | Avg infer / 30s sample | Avg RTF | Keyword hit rate | Whole-GPU used avg / peak | GPU util avg / peak | Container RAM avg / peak |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `moss_audio_8b_instruct` | none | 94.5s | 17.3 / 17.3 GiB | 3.086s | 0.103 | 0.182 | 19.7 / 19.9 GiB | 31.0% / 80.0% | 1.32 / 1.60 GiB |
| `moss_audio_8b_instruct_bnb8` | bitsandbytes 8bit | 102.2s | 9.6 / 11.0 GiB | 12.602s | 0.421 | 0.091 | 13.6 / 13.6 GiB | 28.7% / 50.0% | 3.12 / 3.13 GiB |
| `moss_audio_8b_instruct_bnb4` | bitsandbytes 4bit NF4 | 102.2s | 6.1 / 8.7 GiB | 58.628s | 1.959 | 0.136 | 11.3 / 11.3 GiB | 52.1% / 72.0% | 3.40 / 3.53 GiB |

Raw files:

- `output/test/asr-bench/results/http_compare_moss_instruct_fp16_solo_20260505.json`
- `output/test/asr-bench/results/http_compare_moss_instruct_bnb8_solo_rerun_20260505.json`
- `output/test/asr-bench/results/http_compare_moss_instruct_bnb4_solo_20260505.json`
- `output/test/asr-bench/results/resource_moss_instruct_fp16_solo_20260505.jsonl`
- `output/test/asr-bench/results/resource_moss_instruct_bnb8_solo_rerun_20260505.jsonl`
- `output/test/asr-bench/results/resource_moss_instruct_bnb4_solo_20260505.jsonl`

Quantization takeaway:

- 8bit reduces isolated whole-GPU peak from about `19.9 GiB` to `13.6 GiB`, saving roughly `6.3 GiB`, but inference becomes about `4.1x` slower and keyword hits drop on this small sample.
- 4bit reduces isolated whole-GPU peak further to about `11.3 GiB`, but it is not usable in this setup: two samples produced repetition/degeneration and average RTF exceeded realtime.
- Best usable MOSS option from this pass is Instruct 8bit only if the deployment needs the memory saving more than the speed. For throughput and transcript stability, non-quantized Instruct remains better.

## RoughCut Default ASR Replacement

Decision: replace VibeVoice as RoughCut's default local HTTP ASR service with non-quantized `MOSS-Audio-8B-Instruct`.

Implementation notes:

- RoughCut keeps provider key `local_http_asr`, but the default model and endpoint now point to MOSS.
- MOSS Docker service exposes a RoughCut-compatible `POST /transcribe` multipart endpoint in addition to `/generate`.
- The compatible endpoint forwards filename/prompt hotwords into the MOSS instruction prompt.
- Default Docker guard target is now `docker-compose.moss-audio.yml` service `moss-audio-8b-instruct`.
- Current `.env` and compose defaults use `http://127.0.0.1:30080` on the host and `http://host.docker.internal:30080` from RoughCut containers.

Smoke test:

- Input: `output/test/asr-bench/samples/20260212-141536_补充说明noc_mt34开箱的快开自定义方式_30s.wav`
- Provider result: `provider=local_http_asr`, `model=moss-audio-8b-instruct`, `duration=29.933`, `segments=2`
- Raw smoke output: `output/test/asr-bench/results/roughcut_moss_provider_smoke_20260505.json`

## Queue Restart Test

Existing queued job restarted through `POST /api/v1/jobs/7b4ca848-d4dc-41e0-bacf-800d1a5cbc8a/restart`.

Observed issue:

- The job's historical config snapshot still pointed at `local-asr-current` / `http://127.0.0.1:6001` / `VibeVoice INT8`.
- First retry therefore failed at the old VibeVoice endpoint.

Fix:

- Legacy local HTTP ASR snapshots are normalized to the current MOSS defaults during runtime override normalization.
- New defaults are `moss-audio-8b-instruct`, `http://127.0.0.1:30080`, and display name `MOSS-Audio 8B Instruct`.

Validated flow:

- `probe`: done
- `extract_audio`: done
- `transcribe`: done through `http://127.0.0.1:30080/transcribe`
- Transcribe result: 8 chunks, 479.701s audio, 170 transcript segments, 138.629s worker elapsed
- `subtitle_postprocess`: done, 170 transcript segments to 164 subtitle items, subtitle quality score 95.61
- Follow-up gates `subtitle_term_resolution`, `subtitle_consistency_review`, `glossary_review`, and `transcript_review` also completed before the temporary local workers were stopped.

## Third-Party Quantized Weights

No credible third-party quantized replacement for `OpenMOSS-Team/MOSS-Audio-8B-Instruct` was found during this pass.

Checked Hugging Face searches:

- `MOSS-Audio-8B-Instruct`: official `OpenMOSS-Team/MOSS-Audio-8B-Instruct` and a mirror-like `sishuiliunianfrweffe/MOSS-Audio-8B-Instruct`
- `MOSS-Audio AWQ`: no results
- `MOSS-Audio GPTQ`: no results
- `MOSS-Audio GGUF`: no results
- `OpenMOSS quantized`: no results
- `MOSS-Audio 8B quantized`: no results

The only adjacent quantized artifact found was `mlx-community/MOSS-Audio-Tokenizer-MLX-8bit`, which is an audio tokenizer artifact, not a deployable `MOSS-Audio-8B-Instruct` ASR model.

## Idle GPU Release

MOSS-Audio Docker service now supports automatic idle unload:

- Default: `MOSS_AUDIO_IDLE_UNLOAD_SECONDS=10`
- `GET /health` reports `loaded`, `load_count`, idle timing, and CUDA memory stats.
- `POST /unload` immediately unloads the model and clears CUDA cache.
- After idle unload, the container remains running; the next `/generate` or `/transcribe` request reloads the model lazily.
