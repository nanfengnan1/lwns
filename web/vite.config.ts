import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = env.ROUTE_OVS_API_TARGET || "http://127.0.0.1:8090";
  return {
    plugins: [vue()],
    server: {
      port: 5173,
      strictPort: true,
      proxy: {
        "/api": {
          target,
          changeOrigin: true,
          ws: true,
          configure(proxy) {
            proxy.on("proxyReq", (outgoing, incoming) => {
              // Translate only same-origin requests from the dev page. Keep
              // foreign origins intact so the Python backend still rejects them.
              if (
                incoming.headers.origin === `http://${incoming.headers.host}`
              ) {
                outgoing.setHeader("Origin", new URL(target).origin);
              }
            });
            proxy.on("proxyReqWs", (outgoing, incoming) => {
              if (
                incoming.headers.origin === `http://${incoming.headers.host}`
              ) {
                outgoing.setHeader("Origin", new URL(target).origin);
              }
            });
          },
        },
      },
    },
    build: { target: "es2022", sourcemap: false },
  };
});
