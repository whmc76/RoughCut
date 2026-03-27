import { Link } from "react-router-dom";

import { PageHeader } from "../components/ui/PageHeader";
import { PageSection } from "../components/ui/PageSection";
import { AvatarMaterialPanel } from "../features/avatarMaterials/AvatarMaterialPanel";
import { useI18n } from "../i18n";

export function CreatorProfilesPage() {
  const { t } = useI18n();

  return (
    <section className="page-stack">
      <PageHeader
        eyebrow={t("creator.page.eyebrow")}
        title={t("creator.page.title")}
        description={t("creator.page.description")}
        summary={[
          { label: "页面定位", value: "数字人素材总管", detail: "角色档案、媒体素材和规则约束都集中在这里" },
          { label: "维护原则", value: "先补基础档案，再补素材", detail: "先确保角色信息完整，再追加图片、视频和音频" },
          { label: "输出目标", value: "让任务可直接复用", detail: "整理完成后，任务页可以直接继承数字人能力" },
        ]}
        actions={<Link className="button ghost" to="/creative-modes">{t("creator.page.backToCreativeModes")}</Link>}
      />

      <PageSection
        eyebrow="档案库"
        title="先定位档案，再补资料和素材"
        description="这页现在优先解决“快速找到要维护的创作者档案”，然后再进入详情做补充、预览和激活。"
      >
        <AvatarMaterialPanel />
      </PageSection>
    </section>
  );
}
