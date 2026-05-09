import axios from "axios";

const BASE = import.meta.env.VITE_API_BASE as string;
export const WS_BASE = import.meta.env.VITE_WS_BASE as string;

if (!BASE) throw new Error("VITE_API_BASE 未设置，请检查 .env 文件");

export const api = axios.create({
  baseURL: BASE,
  withCredentials: true,
});

// CSRF：从 cookie 读 csrf_token 写入请求头
api.interceptors.request.use((config) => {
  const match = document.cookie
    .split("; ")
    .find((row) => row.startsWith("csrf_token="));
  const token = match?.split("=")[1];
  if (token && ["post", "delete", "put", "patch"].includes(config.method ?? "")) {
    config.headers["X-CSRF-Token"] = decodeURIComponent(token);
  }
  return config;
});

// 401 / 403 → 跳登录
api.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err.response?.status;
    if ((status === 401 || status === 403) && window.location.pathname !== "/login") {
      window.location.href = "/login";
    }
    return Promise.reject(err);
  }
);