import { useState } from "react";
import {
  useAccount,
  useChainId,
  useConnect,
  useDisconnect,
  useSwitchChain,
} from "wagmi";
import { besuTestnet } from "./lib/chain";
import { shortAddr } from "./lib/format";
import { NAV, type Page } from "./lib/nav";
import Home from "./pages/Home";
import DefenderCenter from "./pages/DefenderCenter";
import AttackerCenter from "./pages/AttackerCenter";
import MiningCenter from "./pages/MiningCenter";
import Leaderboard from "./pages/Leaderboard";
import Faucet from "./pages/Faucet";
import DataMarket from "./pages/DataMarket";

export default function App() {
  const [page, setPage] = useState<Page>("home");
  const { address, isConnected } = useAccount();
  const { connect, connectors, isPending: connecting } = useConnect();
  const { disconnect } = useDisconnect();
  const chainId = useChainId();
  const { switchChain } = useSwitchChain();

  return (
    <div className="shell">
      <header className="topbar">
        <button className="wordmark" onClick={() => setPage("home")}>
          REDTEAM<span>//ARENA</span>
        </button>
        <nav className="nav">
          {NAV.map((item) => (
            <button
              key={item.id}
              className={page === item.id ? "nav-link active" : "nav-link"}
              onClick={() => setPage(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <div className="wallet">
          {isConnected && chainId !== besuTestnet.id && (
            <button
              className="btn ghost small"
              onClick={() => switchChain({ chainId: besuTestnet.id })}
            >
              切到 48850
            </button>
          )}
          {isConnected ? (
            <button className="btn ghost small" onClick={() => disconnect()}>
              {shortAddr(address)} · 断开
            </button>
          ) : (
            <button
              className="btn small"
              disabled={connecting || connectors.length === 0}
              onClick={() => connectors[0] && connect({ connector: connectors[0] })}
            >
              {connecting ? "连接中…" : "连接钱包"}
            </button>
          )}
        </div>
      </header>

      <main className="content">
        {page === "home" && <Home onNavigate={setPage} />}
        {page === "defender" && <DefenderCenter />}
        {page === "attacker" && <AttackerCenter />}
        {page === "mining" && <MiningCenter />}
        {page === "leaderboard" && <Leaderboard />}
        {page === "faucet" && <Faucet />}
        {page === "market" && <DataMarket />}
      </main>

      <footer className="footer">
        <span>REDTEAM · 防御性安全评测 · Besu 测试网 48850</span>
        <span>测试网资产无价值；所有攻防数据仅用于防御研究。</span>
      </footer>
    </div>
  );
}
