import { Link } from "react-router-dom";

import { PageHeader } from "../components/ui/PageHeader";
import { AvatarMaterialPanel } from "../features/avatarMaterials/AvatarMaterialPanel";
import { useI18n } from "../i18n";

export function CreatorProfilesPage() {
  const { t } = useI18n();

  return (
    <section>
      <PageHeader
        eyebrow={t("creator.page.eyebrow")}
        title={t("creator.page.title")}
        description={t("creator.page.description")}
        actions={<Link className="button ghost" to="/creative-modes">{t("creator.page.backToCreativeModes")}</Link>}
      />

      <AvatarMaterialPanel />
    </section>
  );
}
