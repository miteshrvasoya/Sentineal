"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import TourProvider from "@/components/TourProvider";
import { ModeProvider } from "@/lib/mode";

export default function Providers({ children }: { children: React.ReactNode }) {
  const [qc] = useState(() => new QueryClient({ defaultOptions: { queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false } } }));
  return <QueryClientProvider client={qc}><ModeProvider><TourProvider>{children}</TourProvider></ModeProvider></QueryClientProvider>;
}
