/**
 * CORS for the public /rpc proxy.
 *
 * Wallet extensions call the RPC from a chrome-extension:// / moz-extension://
 * origin, not from the page origin. Besu happens to answer CORS when it runs
 * with --rpc-http-cors-origins=*, but the BFF must not depend on an upstream
 * flag: without these headers the wallet's fetch fails with the opaque
 * "Failed to fetch" even though server-side probes of /rpc return 200.
 *
 * The origin is echoed instead of "*" so a wallet that fetches with
 * credentials still passes the CORS check. /rpc carries no cookies and no
 * platform token, so there is nothing to leak.
 */

export function rpcCors(req, res) {
  const origin = req.get("origin");
  if (origin) {
    res.setHeader("Access-Control-Allow-Origin", origin);
    res.setHeader("Access-Control-Allow-Credentials", "true");
    res.setHeader("Vary", "Origin");
  }
  res.setHeader("Access-Control-Allow-Methods", "POST, GET, OPTIONS");
  // Reflect the wallet's requested headers (content-type is the common one)
  // instead of keeping a fixed list that a future wallet may exceed.
  const requested = req.get("access-control-request-headers");
  res.setHeader(
    "Access-Control-Allow-Headers",
    requested || "content-type, authorization",
  );
  res.setHeader("Access-Control-Max-Age", "600");
}

/** Answer preflights locally so they never reach Besu. */
export function rpcCorsMiddleware(req, res, next) {
  rpcCors(req, res);
  if (req.method === "OPTIONS") {
    res.status(204).end();
    return;
  }
  next();
}
