/**
 * Production BFF for RTM Arena.
 *
 * - Serves the built SPA from dist/
 * - Injects PLATFORM_API_TOKEN server-side (the browser never sees it)
 * - Requires X-Admin-Key for the two operator endpoints
 * - Proxies /rpc so the dApp can use a same-origin RPC
 *
 * Run: PLATFORM_API_TOKEN=... PLATFORM_ADMIN_KEY=... node server.mjs
 */

import crypto from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";
import express from "express";
import compression from "compression";
import { createProxyMiddleware } from "http-proxy-middleware";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT || 3000);
const HOST = process.env.HOST || "0.0.0.0";
const API_URL = process.env.PLATFORM_API_URL || "http://127.0.0.1:8080";
const RPC_URL = process.env.PLATFORM_RPC_URL || "http://127.0.0.1:8546";
const API_TOKEN = process.env.PLATFORM_API_TOKEN || "";
const ADMIN_KEY = process.env.PLATFORM_ADMIN_KEY || "";
const DIST = path.resolve(__dirname, "dist");

if (!API_TOKEN) {
  console.error("[web] PLATFORM_API_TOKEN is required.");
  process.exit(1);
}
if (!ADMIN_KEY) {
  console.warn(
    "[web] PLATFORM_ADMIN_KEY is not set; /api/mining/contests and /api/data/:id/publish will return 403.",
  );
}

function timingSafeEqual(left, right) {
  if (!left || !right) return false;
  const a = Buffer.from(left);
  const b = Buffer.from(right);
  if (a.length !== b.length) return false;
  return crypto.timingSafeEqual(a, b);
}

const ADMIN_ROUTES = [
  { method: "POST", pattern: /^\/api\/mining\/contests\/?$/ },
  { method: "POST", pattern: /^\/api\/data\/[^/]+\/publish\/?$/ },
];

function isAdminRoute(req) {
  // Inside app.use("/api", ...) Express strips the mount path from req.path,
  // so use originalUrl to keep the /api prefix in the match.
  const pathname = (req.originalUrl || req.url || "").split("?")[0];
  return ADMIN_ROUTES.some(
    (route) => route.method === req.method && route.pattern.test(pathname),
  );
}

const buckets = new Map();

setInterval(() => {
  const now = Date.now();
  for (const [key, bucket] of buckets) {
    if (bucket.resetAt <= now) buckets.delete(key);
  }
}, 10 * 60 * 1000).unref();

function rateLimit(name, limit, windowMs) {
  return (req, res, next) => {
    const now = Date.now();
    const key = `${name}:${req.ip}`;
    const bucket = buckets.get(key);
    if (!bucket || bucket.resetAt <= now) {
      buckets.set(key, { count: 1, resetAt: now + windowMs });
      next();
      return;
    }
    if (bucket.count >= limit) {
      res.setHeader("Retry-After", String(Math.ceil((bucket.resetAt - now) / 1000)));
      res.status(429).json({ detail: "too many requests; retry later" });
      return;
    }
    bucket.count += 1;
    next();
  };
}

const app = express();
app.disable("x-powered-by");
if (process.env.TRUST_PROXY === "1") app.set("trust proxy", 1);

app.use(compression());
app.use((req, res, next) => {
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("X-Frame-Options", "DENY");
  res.setHeader("Referrer-Policy", "strict-origin-when-cross-origin");
  res.setHeader("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  next();
});

app.get("/healthz", (_req, res) => {
  res.json({ status: "ok" });
});

// Operator-only platform routes. The key is never forwarded upstream.
app.use("/api", (req, res, next) => {
  if (!isAdminRoute(req)) {
    next();
    return;
  }
  if (!ADMIN_KEY || !timingSafeEqual(req.get("x-admin-key"), ADMIN_KEY)) {
    res.status(403).json({ detail: "admin key required" });
    return;
  }
  next();
});

app.post(
  "/api/faucet/ticket",
  rateLimit("faucet", 10, 60 * 60 * 1000),
  (_req, _res, next) => next(),
);

app.post(
  "/api/faucet/claim",
  rateLimit("faucet-claim", 10, 60 * 60 * 1000),
  (_req, _res, next) => next(),
);

app.post(
  "/api/defenders/register",
  rateLimit("register", 6, 60 * 60 * 1000),
  (_req, _res, next) => next(),
);

const apiProxy = createProxyMiddleware({
  target: API_URL,
  changeOrigin: true,
  pathRewrite: { "^/api": "" },
  headers: { Authorization: `Bearer ${API_TOKEN}` },
  proxyTimeout: 180_000,
  timeout: 180_000,
  on: {
    proxyReq: (proxyReq) => {
      proxyReq.removeHeader("x-admin-key");
    },
    error: (error, _req, res) => {
      console.error("[web] API proxy error:", error.message);
      if (res && !res.headersSent) {
        res.writeHead(502, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ detail: "platform API unavailable" }));
      } else if (res) {
        res.destroy();
      }
    },
  },
});

const rpcProxy = createProxyMiddleware({
  target: RPC_URL,
  changeOrigin: true,
  pathRewrite: { "^/rpc": "" },
  proxyTimeout: 60_000,
  timeout: 60_000,
  on: {
    error: (error, _req, res) => {
      console.error("[web] RPC proxy error:", error.message);
      if (res && !res.headersSent) {
        res.writeHead(502, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: "RPC unavailable" }));
      } else if (res) {
        res.destroy();
      }
    },
  },
});

app.use("/api", apiProxy);
app.use("/rpc", rpcProxy);
app.use(
  "/assets",
  express.static(path.join(DIST, "assets"), {
    immutable: true,
    maxAge: "1y",
    fallthrough: true,
  }),
);
app.use(
  express.static(DIST, {
    index: false,
    maxAge: 0,
    setHeaders: (res) => res.setHeader("Cache-Control", "no-cache"),
  }),
);

app.use((req, res, next) => {
  if (req.method !== "GET" && req.method !== "HEAD") {
    next();
    return;
  }
  if (req.path.startsWith("/api") || req.path.startsWith("/rpc")) {
    next();
    return;
  }
  res.sendFile(path.join(DIST, "index.html"), (error) => {
    if (error) next(error);
  });
});

app.use((error, _req, res, _next) => {
  console.error("[web] unhandled error:", error);
  if (!res.headersSent) res.status(500).json({ detail: "internal server error" });
});

const server = app.listen(PORT, HOST, () => {
  console.log(`[web] RTM Arena listening on http://${HOST}:${PORT}`);
  console.log(`[web] API ${API_URL} · RPC ${RPC_URL}`);
});

function shutdown(signal) {
  console.log(`[web] ${signal} received; shutting down`);
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(1), 10_000).unref();
}

process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));
