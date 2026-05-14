import axios from "axios";

const BASE: string = import.meta.env.VITE_API_BASE || "";
const WS_PROTO = window.location.protocol === "https:" ? "wss:" : "ws:";
export const WS_BASE: string = import.meta.env.VITE_WS_BASE || `${WS_PROTO}//${window.location.host}`;

export const api = axios.create({
  baseURL: BASE,
  withCredentials: true,
});

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
