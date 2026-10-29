import { Suspense, lazy, type ReactElement } from "react";
import { Route, Routes } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell";
import Overview from "./pages/Overview";

// 首屏只保留总览；其余页面按路由懒加载，避免把钱包、图表和文档全部塞进
// 同一个近 1 MB 的 bundle（移动端首屏尤其明显）。
const Arena = lazy(() => import("./pages/Arena"));
const ContestDetail = lazy(() => import("./pages/ContestDetail"));
const Defend = lazy(() => import("./pages/Defend"));
const Byoa = lazy(() => import("./pages/Byoa"));
const Mine = lazy(() => import("./pages/Mine"));
const Leaderboard = lazy(() => import("./pages/Leaderboard"));
const Market = lazy(() => import("./pages/Market"));
const MarketDetail = lazy(() => import("./pages/MarketDetail"));
const Faucet = lazy(() => import("./pages/Faucet"));
const Docs = lazy(() => import("./pages/Docs"));
const Ops = lazy(() => import("./pages/Ops"));
const NotFound = lazy(() => import("./pages/NotFound"));

function RouteFallback() {
  return (
    <div
      aria-busy="true"
      aria-live="polite"
      style={{ minHeight: "45vh", display: "grid", placeItems: "center" }}
    >
      <span
        className="mono"
        style={{ opacity: 0.55, fontSize: 12, letterSpacing: "0.14em" }}
      >
        LOADING…
      </span>
    </div>
  );
}

function page(element: ReactElement) {
  return <Suspense fallback={<RouteFallback />}>{element}</Suspense>;
}

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Overview />} />
        <Route path="arena" element={page(<Arena />)} />
        <Route path="arena/:contestId" element={page(<ContestDetail mode="arena" />)} />
        <Route path="defend" element={page(<Defend />)} />
        <Route path="byoa" element={page(<Byoa />)} />
        <Route path="mine" element={page(<Mine />)} />
        <Route path="mine/:contestId" element={page(<ContestDetail mode="mine" />)} />
        <Route path="leaderboard" element={page(<Leaderboard />)} />
        <Route path="market" element={page(<Market />)} />
        <Route path="market/:contestId" element={page(<MarketDetail />)} />
        <Route path="faucet" element={page(<Faucet />)} />
        <Route path="docs" element={page(<Docs />)} />
        <Route path="ops" element={page(<Ops />)} />
        <Route path="*" element={page(<NotFound />)} />
      </Route>
    </Routes>
  );
}
