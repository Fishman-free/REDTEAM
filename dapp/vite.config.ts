import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

/**
 * The browser never receives PLATFORM_API_TOKEN. In development this proxy
 * injects it server-side; in production `server.mjs` does the same.
 */
function readEnvValue(file: string, key: string): string | undefined {
  try {
    const line = readFileSync(file, "utf8")
      .split(/\r?\n/)
      .map((row) => row.trim())
      .find((row) => row.startsWith(`${key}=`));
    if (!line) return undefined;
    return line
      .slice(key.length + 1)
      .trim()
      .replace(/^["']|["']$/g, "") || undefined;
  } catch {
    return undefined;
  }
}

const root = process.cwd();
const platformToken =
  process.env.PLATFORM_API_TOKEN ||
  readEnvValue(resolve(root, "../platform/.env.local"), "PLATFORM_API_TOKEN") ||
  readEnvValue(resolve(root, ".env.local"), "PLATFORM_API_TOKEN");

if (!platformToken) {
  console.warn(
    "[vite] PLATFORM_API_TOKEN not found in ../platform/.env.local; /api requests will be unauthenticated.",
  );
}

const bridgeHeaders = platformToken
  ? { Authorization: `Bearer ${platformToken}` }
  : undefined;

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        // 把变化频率低的依赖拆成独立 chunk：钱包栈（wagmi/viem）与 React
        // 运行时不再和业务页面一起失效，首屏也能并行下载。
        manualChunks(id: string) {
          if (!id.includes("node_modules")) return undefined;
          if (/[\\/]node_modules[\\/](@wagmi|wagmi|viem|@noble|@scure|abitype)[\\/]/.test(id)) {
            return "wallet";
          }
          if (/[\\/]node_modules[\\/](react|react-dom|scheduler|react-router|react-router-dom|@remix-run)[\\/]/.test(id)) {
            return "react";
          }
          if (/[\\/]node_modules[\\/](@tanstack|lucide-react)[\\/]/.test(id)) {
            return "ui";
          }
          return undefined;
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8080",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
        headers: bridgeHeaders,
        timeout: 180_000,
        proxyTimeout: 180_000,
      },
      "/rpc": {
        target: "http://127.0.0.1:8546",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/rpc/, ""),
      },
    },
  },
  preview: {
    port: 4173,
  },
});
