import { useI18n } from "../../lib/i18n";

export function LanguageToggle({ compact = false }: { compact?: boolean }) {
  const { lang, setLang, t } = useI18n();

  return (
    <div
      className={`lang-switch ${compact ? "lang-switch--compact" : ""}`.trim()}
      role="group"
      aria-label={t("Language", "语言")}
    >
      <button
        type="button"
        className={lang === "en" ? "is-active" : ""}
        aria-pressed={lang === "en"}
        onClick={() => setLang("en")}
        title={t("English", "英文")}
      >
        EN
      </button>
      <button
        type="button"
        className={lang === "zh" ? "is-active" : ""}
        aria-pressed={lang === "zh"}
        onClick={() => setLang("zh")}
        title={t("Simplified Chinese", "简体中文")}
      >
        中文
      </button>
    </div>
  );
}
