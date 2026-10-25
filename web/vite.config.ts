import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target =
    env.LWNS_API_TARGET || env.ROUTE_OVS_API_TARGET || "http://127.0.0.1:8090";
  return {
    plugins: [vue()],
    server: {
      port: 5173,
      strictPort: true,
      proxy: {
        "/api": {
          target,
          // Preserve the browser-facing Host and Origin for both HTTP and WS.
          // The backend validates the dev page's origin without translating
          // browser requests into the private upstream's origin.
          changeOrigin: false,
          ws: true,
        },
      },
    },
    build: { target: "es2022", sourcemap: false },
  };
});
