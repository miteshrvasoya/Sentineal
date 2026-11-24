import fs from "node:fs";
import path from "node:path";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Learn | QuantLens" };

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
const text = (c: React.ReactNode): string => (Array.isArray(c) ? c.map(text).join("") : typeof c === "string" ? c : "");

export default function Learn() {
  const md = fs.readFileSync(path.join(process.cwd(), "content", "LEARN.md"), "utf8");
  const toc = md.split("\n").filter((l) => l.startsWith("## ")).map((l) => l.slice(3).trim());
  return (
    <div className="mx-auto max-w-3xl" data-tour="learn-page">
      <nav aria-label="Lessons" className="mb-6 rounded border border-slate-200 p-3 text-sm dark:border-slate-800">
        <b>Lessons</b>
        <ol className="mt-1 grid gap-x-6 sm:grid-cols-2">{toc.map((t) => <li key={t}><a className="text-indigo-600 hover:underline dark:text-indigo-300" href={`#${slug(t)}`}>{t.replace(/^\d+\.\s*/, "")}</a></li>)}</ol>
      </nav>
      <article className="space-y-3 leading-relaxed">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
          h1: ({ children }) => <h1 className="text-3xl font-bold">{children}</h1>,
          h2: ({ children }) => <h2 id={slug(text(children))} className="mt-8 scroll-mt-4 border-b border-slate-200 pb-1 text-xl font-semibold dark:border-slate-800">{children}</h2>,
          ul: ({ children }) => <ul className="list-disc space-y-1 pl-6">{children}</ul>,
          code: ({ children }) => <code className="rounded bg-slate-200 px-1 py-0.5 text-[0.9em] dark:bg-slate-800">{children}</code>,
        }}>{md}</ReactMarkdown>
      </article>
    </div>
  );
}
