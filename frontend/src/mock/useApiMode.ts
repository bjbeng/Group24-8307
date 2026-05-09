import { useState, useCallback } from "react";

export type ApiMode = "mock" | "real";

export function useApiMode() {
  const [mode, setMode] = useState<ApiMode>("mock");

  const toggleMode = useCallback(() => {
    setMode((m) => (m === "mock" ? "real" : "mock"));
  }, []);

  return { mode, setMode, toggleMode };
}