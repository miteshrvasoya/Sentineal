"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

/** Simple mode (default) shows what a beginner needs. Advanced mode shows every analysis tool. */
export type Mode = "simple" | "advanced";
const KEY = "ql-mode";

type Ctx = { mode: Mode; setMode: (m: Mode) => void; ready: boolean };
const ModeCtx = createContext<Ctx>({ mode: "simple", setMode: () => {}, ready: false });
export const useMode = () => useContext(ModeCtx);

export function ModeProvider({ children }: { children: React.ReactNode }) {
  const [mode, setModeState] = useState<Mode>("simple");
  const [ready, setReady] = useState(false);
  useEffect(() => {
    try { if (localStorage.getItem(KEY) === "advanced") setModeState("advanced"); } catch { /* ignore */ }
    setReady(true);
  }, []);
  const setMode = useCallback((m: Mode) => {
    setModeState(m);
    try { localStorage.setItem(KEY, m); } catch { /* ignore */ }
  }, []);
  const v = useMemo(() => ({ mode, setMode, ready }), [mode, setMode, ready]);
  return <ModeCtx.Provider value={v}>{children}</ModeCtx.Provider>;
}
