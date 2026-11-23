import "./globals.css";
import type { Metadata } from "next";
import Providers from "./providers";
import Shell from "@/components/Shell";

export const metadata: Metadata = { title: "QuantLens", description: "Educational market analysis. Not investment advice." };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: `try{var t=localStorage.getItem("theme");if(t==="dark"||(!t&&matchMedia("(prefers-color-scheme: dark)").matches))document.documentElement.classList.add("dark")}catch(e){}` }} />
      </head>
      <body>
        <Providers><Shell>{children}</Shell></Providers>
      </body>
    </html>
  );
}
