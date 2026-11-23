import type { Config } from "tailwindcss";
export default {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: { extend: { colors: { up: "#16a34a", down: "#dc2626" } } },
  plugins: [],
} satisfies Config;
