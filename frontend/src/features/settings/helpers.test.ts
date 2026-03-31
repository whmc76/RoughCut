import { describe, expect, it } from "vitest";

import { getTranscriptionProviderLabel } from "./helpers";

describe("getTranscriptionProviderLabel", () => {
  it("maps transcription providers to named local/api labels", () => {
    expect(getTranscriptionProviderLabel("local_whisper")).toBe("Faster Whisper (local)");
    expect(getTranscriptionProviderLabel("funasr")).toBe("FunASR (local)");
    expect(getTranscriptionProviderLabel("qwen_asr")).toBe("Qwen ASR (local)");
    expect(getTranscriptionProviderLabel("openai")).toBe("OpenAI (api)");
  });
});
