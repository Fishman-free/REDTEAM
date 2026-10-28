import { Route, Routes } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell";
import Overview from "./pages/Overview";
import Arena from "./pages/Arena";
import ContestDetail from "./pages/ContestDetail";
import Defend from "./pages/Defend";
import Mine from "./pages/Mine";
import Leaderboard from "./pages/Leaderboard";
import Market from "./pages/Market";
import MarketDetail from "./pages/MarketDetail";
import Faucet from "./pages/Faucet";
import Ops from "./pages/Ops";
import NotFound from "./pages/NotFound";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Overview />} />
        <Route path="arena" element={<Arena />} />
        <Route path="arena/:contestId" element={<ContestDetail mode="arena" />} />
        <Route path="defend" element={<Defend />} />
        <Route path="mine" element={<Mine />} />
        <Route path="mine/:contestId" element={<ContestDetail mode="mine" />} />
        <Route path="leaderboard" element={<Leaderboard />} />
        <Route path="market" element={<Market />} />
        <Route path="market/:contestId" element={<MarketDetail />} />
        <Route path="faucet" element={<Faucet />} />
        <Route path="ops" element={<Ops />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
