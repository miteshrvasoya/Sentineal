"use client";
export default function ThemeToggle() {
  return (
    <button aria-label="Toggle theme" className="ml-auto rounded bg-slate-200 px-2 py-1 text-sm dark:bg-slate-800"
      onClick={() => {
        const dark = document.documentElement.classList.toggle("dark");
        try { localStorage.setItem("theme", dark ? "dark" : "light"); } catch { /* ignore */ }
      }}>Theme</button>
  );
}
