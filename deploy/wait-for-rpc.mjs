const url = process.argv[2] || "http://besu:8545";
const attempts = Number(process.argv[3] || 120);

for (let attempt = 1; attempt <= attempts; attempt += 1) {
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        jsonrpc: "2.0",
        method: "eth_chainId",
        params: [],
        id: attempt,
      }),
    });
    const payload = await response.json();
    if (payload.result) {
      console.log(`[wait-for-rpc] ready: ${payload.result}`);
      process.exit(0);
    }
  } catch {
    // retry
  }
  await new Promise((resolve) => setTimeout(resolve, 2_000));
}

console.error(`[wait-for-rpc] RPC not ready after ${attempts} attempts: ${url}`);
process.exit(1);
