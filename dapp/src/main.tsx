import { Component, StrictMode, type ErrorInfo, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { WagmiProvider } from "wagmi";
import App from "./App";
import { wagmiConfig } from "./lib/chain";
import { I18nProvider, getLang } from "./lib/i18n";
import { PlatformProvider } from "./lib/platform";
import { ToastProvider } from "./context/ToastContext";
import { ActivityProvider } from "./context/ActivityContext";
import "@fontsource-variable/bricolage-grotesque";
import "@fontsource-variable/ibm-plex-sans";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/ibm-plex-mono/600.css";
import "./theme.css";
import "./supplement.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 10_000,
      refetchOnWindowFocus: false,
    },
    mutations: {
      retry: 0,
    },
  },
});

class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("RTM Arena render error", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      const english = getLang() === "en";
      return (
        <div className="crash-screen">
          <p className="eyebrow">Runtime fault</p>
          <h1>{english ? "The interface hit an unhandled error" : "界面遇到未处理的错误"}</h1>
          <p>
            {english
              ? "Refreshing the page usually recovers. If the problem persists, check the browser console."
              : "刷新页面通常可以恢复。如果问题持续，请检查浏览器控制台。"}
          </p>
          <pre>{this.state.error.message}</pre>
          <button className="btn btn--primary" onClick={() => window.location.reload()}>
            {english ? "Reload" : "重新加载"}
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <I18nProvider>
        <WagmiProvider config={wagmiConfig}>
          <QueryClientProvider client={queryClient}>
            <PlatformProvider>
              <ToastProvider>
                <ActivityProvider>
                  <BrowserRouter>
                    <App />
                  </BrowserRouter>
                </ActivityProvider>
              </ToastProvider>
            </PlatformProvider>
          </QueryClientProvider>
        </WagmiProvider>
      </I18nProvider>
    </ErrorBoundary>
  </StrictMode>,
);
