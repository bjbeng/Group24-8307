import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Windows 某些环境会对常见端口（如 5173/5174）监听报 EACCES。
  // 这里改用一个更“冷门”的高位端口；若被占用可自行换一个。
  server: { host: "127.0.0.1", port: 30003, strictPort: true },
  // 环境变量前缀
  envPrefix: ["VITE_"],
});
