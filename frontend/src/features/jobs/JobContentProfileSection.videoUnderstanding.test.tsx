// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { I18nProvider } from "../../i18n";
import { JobContentProfileSection } from "./JobContentProfileSection";

afterEach(() => {
  cleanup();
});

describe("JobContentProfileSection video understanding", () => {
  it("renders multimodal understanding and timed semantic spans", () => {
    render(
      <I18nProvider>
        <JobContentProfileSection
          jobId="job-1"
          thumbnailVersion="v1"
          contentProfile={{
            job_id: "job-1",
            status: "pending",
            review_step_status: "pending",
            ocr_evidence: {},
            transcript_evidence: {},
            entity_resolution_trace: {},
            workflow_mode: "standard",
            enhancement_modes: [],
            draft: null,
            final: null,
            memory: null,
          }}
          contentSource={{
            video_type: "tutorial",
            subject_type: "手电",
            video_theme: "对比两支手电的泛光和续航",
            summary: "重点展示照射差异和握持手感。",
            content_understanding: {
              video_type: "tutorial",
              content_domain: "flashlight",
              primary_subject: "手电",
              video_theme: "对比两支手电的泛光和续航",
              summary: "重点展示照射差异和握持手感。",
              evidence_spans: [
                {
                  type: "comparison",
                  timestamp: "00:02-00:05",
                  text: "这里开始正面对比亮度。",
                },
              ],
              timed_focus_spans: [
                {
                  type: "hook",
                  timestamp: "00:00-00:02",
                  text: "先抛出哪支更适合夜骑的问题。",
                },
              ],
            },
            video_understanding: {
              global_understanding: {
                video_type: "tutorial",
                content_domain: "flashlight",
                video_theme: "对比两支手电的泛光和续航",
                summary: "重点展示照射差异和握持手感。",
                primary_subject: { name: "夜骑手电" },
                style_profile: {
                  pace: "fast",
                  information_density: "high",
                },
                narrative_structure: [
                  {
                    label: "hook",
                    start: 0,
                    end: 2,
                  },
                  {
                    label: "comparison",
                    start: 2,
                    end: 5,
                  },
                ],
              },
            },
          }}
          contentDraft={{}}
          contentKeywords=""
          isSaving={false}
          showThumbnails={false}
          onFieldChange={() => undefined}
          onKeywordsChange={() => undefined}
          onConfirm={() => undefined}
        />
      </I18nProvider>,
    );

    expect(screen.getByTestId("video-understanding-card")).toBeInTheDocument();
    expect(screen.getByText("视频理解")).toBeInTheDocument();
    expect(screen.getByText("对比两支手电的泛光和续航")).toBeInTheDocument();
    expect(screen.getByText("主体：夜骑手电")).toBeInTheDocument();
    expect(screen.getByText("领域：flashlight")).toBeInTheDocument();
    expect(screen.getByText("节奏 fast")).toBeInTheDocument();
    expect(screen.getByText(/00:00-00:02 开场 Hook/)).toBeInTheDocument();

    expect(screen.getByTestId("semantic-spans-card")).toBeInTheDocument();
    expect(screen.getByText("时间证据")).toBeInTheDocument();
    expect(screen.getByText("先抛出哪支更适合夜骑的问题。")).toBeInTheDocument();
    expect(screen.getByText("这里开始正面对比亮度。")).toBeInTheDocument();
    expect(screen.getByText("00:00-00:02")).toBeInTheDocument();
    expect(screen.getByText("00:02-00:05")).toBeInTheDocument();
  });
});
