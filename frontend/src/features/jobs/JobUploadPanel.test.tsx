import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";

import { JobUploadPanel } from "./JobUploadPanel";

vi.mock("../../i18n", () => ({
  useI18n: () => ({
    t: (key: string) =>
      (
        {
          "jobs.upload.title": "新建任务",
          "jobs.upload.description": "上传任务",
          "jobs.upload.file": "视频文件",
          "jobs.upload.language": "语言",
          "jobs.upload.channelProfile": "默认模板",
          "jobs.upload.outputDir": "输出目录",
          "jobs.upload.workflowMode": "基础模式",
          "jobs.upload.enhancements": "增强模式",
          "jobs.upload.submit": "上传并创建任务",
          "jobs.upload.submitting": "正在创建...",
          "jobs.upload.videoDescription": "视频说明",
          "jobs.upload.videoDescriptionPlaceholder": "填写说明",
          "jobs.upload.previewTitle": "回看原视频",
          "jobs.upload.previewDescription": "补充任务说明时可以直接回看刚选中的视频素材。",
          "jobs.upload.previewEmpty": "选择视频文件后，这里会显示可直接播放的预览。",
        } satisfies Record<string, string>
      )[key] ?? key,
  }),
}));

vi.mock("../../components/ui/PanelHeader", () => ({
  PanelHeader: ({ title, description }: { title: string; description?: string }) => (
    <div>
      <strong>{title}</strong>
      {description ? <span>{description}</span> : null}
    </div>
  ),
}));

vi.mock("../../components/forms/SelectField", () => ({
  SelectField: ({ label, value }: { label: string; value: string }) => (
    <label>
      <span>{label}</span>
      <input value={value} readOnly />
    </label>
  ),
}));

vi.mock("../../components/forms/CheckboxField", () => ({
  CheckboxField: ({ label, checked }: { label: string; checked: boolean }) => (
    <label>
      <span>{label}</span>
      <input type="checkbox" checked={checked} readOnly />
    </label>
  ),
}));

vi.mock("../../components/forms/Field", () => ({
  Field: ({ label, children }: { label: string; children: ReactNode }) => (
    <label>
      <span>{label}</span>
      {children}
    </label>
  ),
}));

function buildProps(file: File | null = null) {
  return {
    upload: {
      file,
      language: "zh-CN",
      workflowTemplate: "",
      workflowMode: "standard_edit",
      enhancementModes: [],
      outputDir: "",
      videoDescription: "",
    },
    languageOptions: [{ value: "zh-CN", label: "简体中文" }],
    workflowTemplateOptions: [{ value: "", label: "自动匹配" }],
    workflowModeOptions: [{ value: "standard_edit", label: "标准成片" }],
    enhancementOptions: [],
    onChange: vi.fn(),
    onSubmit: vi.fn(),
    isSubmitting: false,
  };
}

describe("JobUploadPanel", () => {
  beforeEach(() => {
    Object.defineProperty(URL, "createObjectURL", {
      writable: true,
      configurable: true,
      value: vi.fn(),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      writable: true,
      configurable: true,
      value: vi.fn(),
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows an inline video preview for the selected file", () => {
    const createObjectURL = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:preview-demo");
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});

    render(<JobUploadPanel {...buildProps(new File(["video"], "demo.mp4", { type: "video/mp4" }))} />);

    expect(screen.getByText("回看原视频")).toBeInTheDocument();
    expect(screen.getByTestId("job-upload-video-preview")).toHaveAttribute("src", "blob:preview-demo");
    expect(screen.getByText("demo.mp4")).toBeInTheDocument();
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).not.toHaveBeenCalled();
  });

  it("releases the preview URL when the selected file is cleared", () => {
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:preview-demo");
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});

    const { rerender } = render(<JobUploadPanel {...buildProps(new File(["video"], "demo.mp4", { type: "video/mp4" }))} />);

    rerender(<JobUploadPanel {...buildProps(null)} />);

    expect(screen.queryByTestId("job-upload-video-preview")).not.toBeInTheDocument();
    expect(screen.getByText("选择视频文件后，这里会显示可直接播放的预览。")).toBeInTheDocument();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:preview-demo");
  });
});
