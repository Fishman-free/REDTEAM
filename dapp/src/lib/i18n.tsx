import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type Lang = "en" | "zh";

export const DEFAULT_LANG: Lang = "en";
const STORAGE_KEY = "rtm.lang.v1";

function isLang(value: string | null): value is Lang {
  return value === "en" || value === "zh";
}

function storedLang(): Lang {
  if (typeof window === "undefined") return DEFAULT_LANG;
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    return isLang(saved) ? saved : DEFAULT_LANG;
  } catch {
    return DEFAULT_LANG;
  }
}

// Module-level mirror for helpers that run outside React (formatting, error
// translation and the API client). The provider keeps it in sync.
let activeLang: Lang = storedLang();

export function getLang(): Lang {
  return activeLang;
}

export function locale(): string {
  return activeLang === "en" ? "en-US" : "zh-CN";
}

interface I18nValue {
  lang: Lang;
  setLang: (lang: Lang) => void;
  toggleLang: () => void;
  /** Pick the English or Chinese copy for the active language. */
  t: (en: string, zh: string) => string;
}

const I18nContext = createContext<I18nValue | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(storedLang);

  useEffect(() => {
    activeLang = lang;
    document.documentElement.lang = lang === "en" ? "en" : "zh-CN";
    try {
      window.localStorage.setItem(STORAGE_KEY, lang);
    } catch {
      // Language still works for this session when storage is unavailable.
    }
  }, [lang]);

  const setLang = useCallback((next: Lang) => {
    activeLang = next;
    setLangState(next);
  }, []);

  const toggleLang = useCallback(() => {
    activeLang = activeLang === "en" ? "zh" : "en";
    setLangState(activeLang);
  }, []);

  const t = useCallback((en: string, zh: string) => (lang === "en" ? en : zh), [lang]);

  const value = useMemo(
    () => ({ lang, setLang, toggleLang, t }),
    [lang, setLang, t, toggleLang],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const context = useContext(I18nContext);
  if (!context) throw new Error("useI18n must be used inside I18nProvider");
  return context;
}
