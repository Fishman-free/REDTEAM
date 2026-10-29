// Verify that an existing registry still describes the chain behind the RPC.
// Usage: node check-registry.mjs <registry.json> <rpc-url>
// Exits non-zero (without redeploying) when chainId differs or a contract
// address has no code, e.g. besu-data was reset but rtm-registry was kept.
import { readFileSync } from "node:fs";

const [registryPath = "/registry/addresses.json", url = "http://besu:8545"] =
  process.argv.slice(2);
const FIELDS = ["treasury", "arena", "rtm", "faucet", "dataMarket"];
// TaskSink 只在新部署出现；旧 registry 缺省时跳过，避免阻断滚动升级。
const OPTIONAL_FIELDS = ["taskSink"];

async function rpc(method, params) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", method, params, id: 1 }),
  });
  const payload = await response.json();
  if (payload.error) throw new Error(`${method}: ${payload.error.message}`);
  return payload.result;
}

async function check() {
  const registry = JSON.parse(readFileSync(registryPath, "utf8"));
  const chainId = Number.parseInt(await rpc("eth_chainId", []), 16);
  if (chainId !== registry.chainId) {
    return `chainId mismatch: registry ${registry.chainId}, RPC ${chainId}`;
  }
  const missing = [];
  for (const field of [...FIELDS, ...OPTIONAL_FIELDS]) {
    if (!registry[field]) continue;
    const code = await rpc("eth_getCode", [registry[field], "latest"]);
    if (!code || code === "0x") missing.push(`${field}=${registry[field]}`);
  }
  if (missing.length) return `no contract code at ${missing.join(", ")}`;
  console.log(`[contracts] registry verified on chain ${chainId}`);
  return null;
}

// exitCode instead of process.exit(): exiting with fetch sockets still open
// trips a libuv assertion on Windows Node 24.
const problem = await check();
if (problem) {
  console.error(`[contracts] ${problem}`);
  console.error(
    "[contracts] registry and chain are out of sync; refusing to start. " +
      "If a full reset is intended, confirm and run: bash deploy/down.sh -v && bash deploy/up.sh",
  );
  process.exitCode = 1;
}
