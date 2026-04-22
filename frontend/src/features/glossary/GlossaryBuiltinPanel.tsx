import type { BuiltinGlossaryPack } from "../../types";
import { EmptyState } from "../../components/ui/EmptyState";
import { PanelHeader } from "../../components/ui/PanelHeader";
import { useI18n } from "../../i18n";

type GlossaryBuiltinPanelProps = {
  packs: BuiltinGlossaryPack[];
  filter: string;
  onFilterChange: (domain: string) => void;
  importMode: "add_only" | "sync_aliases";
  onImportModeChange: (mode: "add_only" | "sync_aliases") => void;
  onImportTerm: (pack: BuiltinGlossaryPack, correctForm: string) => void;
  onImportPack: (pack: BuiltinGlossaryPack) => void;
  isImported: (correctForm: string) => boolean;
  isImportingTerm: (correctForm: string) => boolean;
  importingPackDomain: string | null;
};

function domainLabel(domain: string, t: (key: string) => string) {
  const key = `glossary.builtin.domain.${domain}`;
  const value = t(key);
  return value === key ? domain : value;
}

export function GlossaryBuiltinPanel({
  packs,
  filter,
  onFilterChange,
  importMode,
  onImportModeChange,
  onImportTerm,
  onImportPack,
  isImported,
  isImportingTerm,
  importingPackDomain,
}: GlossaryBuiltinPanelProps) {
  const { t } = useI18n();
  const filterOptions = ["all", ...packs.map((pack) => pack.domain)];
  const visiblePacks = packs.filter((pack) => filter === "all" || pack.domain === filter);

  return (
    <section className="panel">
      <PanelHeader
        title={t("glossary.builtin.title")}
        description={t("glossary.builtin.description")}
        actions={
          <div className="builtin-panel-actions">
            <div className="mode-chip-list">
              {filterOptions.map((domain) => (
                <button
                  key={domain}
                  className={`mode-chip filter-chip ${filter === domain ? "selected" : ""}`}
                  type="button"
                  onClick={() => onFilterChange(domain)}
                >
                  {domain === "all" ? t("glossary.builtin.filter.all") : domainLabel(domain, t)}
                </button>
              ))}
            </div>
            <div className="mode-chip-list">
              <button
                className={`mode-chip filter-chip ${importMode === "add_only" ? "selected" : ""}`}
                type="button"
                onClick={() => onImportModeChange("add_only")}
              >
                {t("glossary.builtin.mode.addOnly")}
              </button>
              <button
                className={`mode-chip filter-chip ${importMode === "sync_aliases" ? "selected" : ""}`}
                type="button"
                onClick={() => onImportModeChange("sync_aliases")}
              >
                {t("glossary.builtin.mode.syncAliases")}
              </button>
            </div>
          </div>
        }
      />
      <div className="builtin-pack-grid">
        {visiblePacks.map((pack) => (
          <article key={pack.domain} className="builtin-pack-card">
            <div className="builtin-pack-head">
              <div>
                <div className="row-title">{domainLabel(pack.domain, t)}</div>
                <div className="muted compact-top">
                  {pack.term_count} {t("glossary.builtin.termCount")}
                </div>
              </div>
              {!!pack.presets.length && (
                <div className="mode-chip-list">
                  {pack.presets.map((preset) => (
                    <span key={preset} className="mode-chip subtle">
                      {preset}
                    </span>
                  ))}
                </div>
              )}
            </div>
            <div className="toolbar">
              <button className="button ghost button-sm" type="button" onClick={() => onImportPack(pack)} disabled={importingPackDomain === pack.domain}>
                {importingPackDomain === pack.domain ? t("glossary.builtin.importingPack") : t("glossary.builtin.importPack")}
              </button>
            </div>
            <div className="chip-wrap compact-top">
              {pack.terms.map((term) => (
                <span key={`${pack.domain}-${term.correct_form}`} className="builtin-term-chip" title={term.context_hint || undefined}>
                  <strong>{term.correct_form}</strong>
                  {!!term.wrong_forms.length && <span>{term.wrong_forms.slice(0, 3).join(" / ")}</span>}
                  <button
                    className="button ghost button-sm"
                    type="button"
                    onClick={() => onImportTerm(pack, term.correct_form)}
                    disabled={(isImported(term.correct_form) && importMode === "add_only") || isImportingTerm(term.correct_form)}
                  >
                    {isImported(term.correct_form) && importMode === "add_only"
                      ? t("glossary.builtin.imported")
                      : isImported(term.correct_form) && importMode === "sync_aliases"
                        ? t("glossary.builtin.syncTerm")
                      : isImportingTerm(term.correct_form)
                        ? t("glossary.builtin.importingTerm")
                        : t("glossary.builtin.importTerm")}
                  </button>
                </span>
              ))}
            </div>
          </article>
        ))}
        {!visiblePacks.length && <EmptyState message={t("glossary.builtin.empty")} />}
      </div>
    </section>
  );
}
