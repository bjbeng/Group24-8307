import { api } from "./client";

export interface UserInfo {
  user_id: string;
  username: string;
  nickname: string;
  avatar: string;
}

export const login = (username: string, password: string) =>
  api.post<UserInfo>("/api/auth/login", { username, password });

export const register = (username: string, password: string) =>
  api.post<UserInfo>("/api/auth/register", { username, password });

export const logout = () => api.post("/api/auth/logout");

export const getMe = () => api.get<UserInfo>("/api/auth/me");
