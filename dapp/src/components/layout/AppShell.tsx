import { useEffect, useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  Activity,
  BookOpen,
  Cpu,
  Crosshair,
  Database,
  Droplets,
  LayoutDashboard,
  MoreHorizontal,
  Pickaxe,
  Shield,
  Swords,
  Trophy,
} from "lucide-react";
import { Wordmark } from "../ui/Logo";
import { SyncStatus } from "./SyncStatus";
import { OfflineBanner } from "./OfflineBanner";
import { ActivityDrawer } from "./ActivityDrawer";
import { NetworkBanner } from "../wallet/NetworkBanner";
import { RpcBanner } from "../wallet/RpcBanner";
import { ConnectButton } from "../wallet/ConnectButton";
import { LanguageToggle } from "../ui/LanguageToggle";
import { useActivity } from "../../context/ActivityContext";
import { usePlatform } from "../../lib/platform";
import { useI18n } from "../../lib/i18n";
import { useDocumentTitle } from "../../lib/hooks";
import { Dialog } from "../ui/Dialog";

interface NavItem {
  to: string;
  en: string;
  zh: string;
  icon: ReactNode;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

const GROUPS: NavGroup[] = [
  {
    label: "OPERATIONS",
    items: [
      { to: "/", en: "Overview", zh: "总览", icon: <LayoutDashboard size={16} /> },
      { to: "/arena", en: "Arena", zh: "竞技场", icon: <Swords size={16} /> },
      { to: "/defend", en: "Defend", zh: "守方", icon: <Shield size={16} /> },
      { to: "/byoa", en: "BYOA", zh: "自带 agent", icon: <Cpu size={16} /> },
      { to: "/mine", en: "Mine", zh: "挖矿", icon: <Pickaxe size={16} /> },
    ],
  },
  {
    label: "INTELLIGENCE",
    items: [
      { to: "/leaderboard", en: "Ranks", zh: "排行榜", icon: <Trophy size={16} /> },
      { to: "/market", en: "Market", zh: "数据市场", icon: <Database size={16} /> },
    ],
  },
  {
    label: "SUPPORT",
    items: [
      { to: "/faucet", en: "Faucet", zh: "测试水龙头", icon: <Droplets size={16} /> },
      { to: "/docs", en: "Guide", zh: "使用文档", icon: <BookOpen size={16} /> },
    ],
  },
];

const MOBILE_PRIMARY: NavItem[] = [
  { to: "/", en: "Home", zh: "总览", icon: <LayoutDashboard size={18} /> },
  { to: "/arena", en: "Arena", zh: "竞技场", icon: <Swords size={18} /> },
  { to: "/defend", en: "Defend", zh: "守方", icon: <Shield size={18} /> },
  { to: "/byoa", en: "BYOA", zh: "自带 agent", icon: <Cpu size={18} /> },
  { to: "/mine", en: "Mine", zh: "挖矿", icon: <Pickaxe size={18} /> },
];

const MOBILE_MORE: NavItem[] = [
  { to: "/leaderboard", en: "Ranks", zh: "排行榜", icon: <Trophy size={17} /> },
  { to: "/market", en: "Market", zh: "数据市场", icon: <Database size={17} /> },
  { to: "/faucet", en: "Faucet", zh: "测试水龙头", icon: <Droplets size={17} /> },
  { to: "/docs", en: "Guide", zh: "使用文档", icon: <BookOpen size={17} /> },
];

function pageTitle(pathname: string): { en: string; zh: string } {
  if (pathname === "/") return { en: "Overview", zh: "作战总览" };
  if (pathname.startsWith("/arena/")) return { en: "Contest", zh: "战场详情" };
  if (pathname === "/arena") return { en: "Arena", zh: "竞技场" };
  if (pathname === "/defend") return { en: "Defend", zh: "守方计划" };
  if (pathname === "/byoa") return { en: "BYOA", zh: "守方自带 agent" };
  if (pathname.startsWith("/mine/")) return { en: "Mining", zh: "挖矿战场" };
  if (pathname === "/mine") return { en: "Mine", zh: "挖矿中心" };
  if (pathname === "/leaderboard") return { en: "Ranks", zh: "排行榜" };
  if (pathname.startsWith("/market/")) return { en: "Dataset", zh: "数据详情" };
  if (pathname === "/market") return { en: "Market", zh: "数据市场" };
  if (pathname === "/faucet") return { en: "Faucet", zh: "测试水龙头" };
  if (pathname === "/docs") return { en: "Guide", zh: "使用文档" };
  if (pathname === "/ops") return { en: "Operations", zh: "运营控制台" };
  return { en: "Unknown", zh: "未找到页面" };
}

function SidebarStatus() {
  const { meta, online, status } = usePlatform();
  const { t } = useI18n();
  const lastBlock = status?.indexer?.lastBlock;
  const lag = status?.indexer?.lag;

  return (
    <div className="sidebar-status">
      <div className="sidebar-status__head">
        <span className={`status-dot ${online ? "is-live" : "is-offline"}`} />
        <span className="mono">{online ? "LINK ACTIVE" : "LINK LOST"}</span>
      </div>
      <dl className="sidebar-status__grid">
        <div>
          <dt>NETWORK</dt>
          <dd>{meta.network}</dd>
        </div>
        <div>
          <dt>CHAIN</dt>
          <dd className="mono">{meta.chainId}</dd>
        </div>
        <div>
          <dt>BLOCK</dt>
          <dd className="mono">
            {lastBlock !== null && lastBlock !== undefined
              ? lastBlock.toLocaleString("en-US")
              : "—"}
          </dd>
        </div>
        <div>
          <dt>LAG</dt>
          <dd className={`mono ${typeof lag === "number" && lag > 8 ? "is-warning" : ""}`}>
            {typeof lag === "number" ? `${lag} blk` : "—"}
          </dd>
        </div>
      </dl>
      <NavLink to="/faucet" className="sidebar-status__link">
        <Droplets size={12} />
        {t("Testnet faucet", "测试网水龙头")}
        <span aria-hidden="true">→</span>
      </NavLink>
    </div>
  );
}

function Sidebar() {
  const { t, lang } = useI18n();
  return (
    <aside className="sidebar">
      <NavLink to="/" className="sidebar__brand" aria-label={t("RTM Arena home", "RTM Arena 首页")}>
        <Wordmark />
      </NavLink>
      <div className="sidebar__divider" />
      <nav className="sidebar__nav" aria-label={t("Main navigation", "主导航")}>
        {GROUPS.map((group) => (
          <div className="nav-group" key={group.label}>
            <p className="nav-group__label">{group.label}</p>
            {group.items.map((item, index) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  `nav-item ${isActive ? "is-active" : ""}`.trim()
                }
              >
                <span className="nav-item__icon" aria-hidden="true">
                  {item.icon}
                </span>
                <span className="nav-item__text">
                  <span className="nav-item__label">{t(item.en, item.zh)}</span>
                  {lang === "zh" && <span className="nav-item__en">{item.en}</span>}
                </span>
                <span className="nav-item__index mono">{String(index + 1).padStart(2, "0")}</span>
              </NavLink>
            ))}
          </div>
        ))}
      </nav>
      <div className="sidebar__spacer" />
      <SidebarStatus />
      <div className="sidebar__foot">
        <Crosshair size={12} />
        <span>DEFENSIVE SECURITY RESEARCH</span>
      </div>
    </aside>
  );
}

function MobileNav({ onMore }: { onMore: () => void }) {
  const { t } = useI18n();
  const location = useLocation();
  const moreActive = MOBILE_MORE.some((item) => location.pathname.startsWith(item.to));
  return (
    <nav className="mobile-nav" aria-label={t("Mobile navigation", "移动端导航")}>
      {MOBILE_PRIMARY.map((item) => {
        const active =
          item.to === "/" ? location.pathname === "/" : location.pathname.startsWith(item.to);
        return (
          <NavLink key={item.to} to={item.to} className={`mobile-nav__item ${active ? "is-active" : ""}`}>
            {item.icon}
            <span>{t(item.en, item.zh)}</span>
          </NavLink>
        );
      })}
      <button
        type="button"
        className={`mobile-nav__item ${moreActive ? "is-active" : ""}`}
        onClick={onMore}
      >
        <MoreHorizontal size={18} />
        <span>{t("More", "更多")}</span>
      </button>
    </nav>
  );
}

function MobileMoreDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const { t, lang } = useI18n();
  return (
    <Dialog open={open} onClose={onClose} title={t("More", "更多")} eyebrow="Navigation" size="sm">
      <div className="more-list">
        {MOBILE_MORE.map((item) => (
          <button
            key={item.to}
            type="button"
            className="more-list__item"
            onClick={() => {
              onClose();
              navigate(item.to);
            }}
          >
            <span className="more-list__icon">{item.icon}</span>
            <span>
              <strong>{t(item.en, item.zh)}</strong>
              {lang === "zh" && <small>{item.en}</small>}
            </span>
            <span className="more-list__arrow" aria-hidden="true">→</span>
          </button>
        ))}
        <div className="more-list__note">
          <BookOpen size={14} />
          <span>
            {t(
              "Testnet assets have no value. All attack data is used for defensive research only.",
              "测试网资产无价值。所有攻防数据只用于防御研究。",
            )}
          </span>
        </div>
      </div>
    </Dialog>
  );
}

export function AppShell() {
  const location = useLocation();
  const [activityOpen, setActivityOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const { pendingCount } = useActivity();
  const { t, lang } = useI18n();
  const title = pageTitle(location.pathname);
  const localizedTitle = lang === "en" ? title.en : title.zh;
  const networkFreePage = location.pathname === "/faucet" || location.pathname === "/docs";
  useDocumentTitle(`${localizedTitle} · RTM Arena`);

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
    setMoreOpen(false);
  }, [location.pathname]);

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        {t("Skip to main content", "跳到主要内容")}
      </a>
      <Sidebar />
      <div className="app-main">
        <header className="topbar">
          <NavLink to="/" className="topbar__brand" aria-label={t("RTM Arena home", "RTM Arena 首页")}>
            <Wordmark compact />
          </NavLink>
          <div className="topbar__title">
            <span className="topbar__en mono">
              {lang === "zh" ? title.en : t("Field operations", "现场操作")}
            </span>
            <span className="topbar__divider" aria-hidden="true">/</span>
            <h1>{localizedTitle}</h1>
          </div>
          <div className="topbar__actions">
            <LanguageToggle />
            <div className="topbar__sync">
              <SyncStatus />
            </div>
            <button
              type="button"
              className="icon-btn icon-btn--badged"
              onClick={() => setActivityOpen(true)}
              aria-label={t("Open transaction activity", "打开交易活动")}
              title={t("Transaction activity", "交易活动")}
            >
              <Activity size={17} />
              {pendingCount > 0 && <span className="icon-btn__badge">{pendingCount}</span>}
            </button>
            <ConnectButton size="sm" label={t("Connect", "连接")} />
          </div>
        </header>
        {!networkFreePage && <NetworkBanner />}
        {!networkFreePage && <RpcBanner />}
        <OfflineBanner />
        <main className="main" id="main">
          <div className="page" key={location.pathname}>
            <Outlet />
          </div>
        </main>
        <footer className="site-footer">
          <div>
            <span className="mono">RTM//ARENA</span>
            <span> · {t("Defensive security evaluation lab", "防御性安全评测实验")}</span>
          </div>
          <div>
            <span>{t("Testnet assets have no value.", "测试网资产无价值。")}</span>
            <span className="mono"> · CHAIN 48850</span>
          </div>
        </footer>
      </div>
      <MobileNav onMore={() => setMoreOpen(true)} />
      <MobileMoreDialog open={moreOpen} onClose={() => setMoreOpen(false)} />
      <ActivityDrawer open={activityOpen} onClose={() => setActivityOpen(false)} />
    </div>
  );
}
