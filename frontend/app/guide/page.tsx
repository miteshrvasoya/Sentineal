import fs from "node:fs";
import path from "node:path";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Metadata } from "next";
import TourButtons from "@/components/TourButtons";

export const metadata: Metadata = { title: "Guide | QuantLens" };

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
const text = (c: React.ReactNode): string => (Array.isArray(c) ? c.map(text).join("") : typeof c === "string" ? c : "");

export default function Guide() {
  const md = fs.readFileSync(path.join(process.cwd(), "content", "GUIDE.md"), "utf8");
  const toc = md.split("\n").filter((l) => l.startsWith("## ")).map((l) => l.slice(3).trim());
  return (
    <div className="mx-auto max-w-4xl">
      <TourButtons />
      <nav aria-label="Guide contents" className="mb-6 rounded border border-slate-200 p-3 text-sm dark:border-slate-800">
        <b>Contents</b>
        <ul className="mt-1 grid gap-x-6 sm:grid-cols-2">
          {toc.map((t) => (
            <li key={t}><a className="text-indigo-600 hover:underline dark:text-indigo-300" href={`#${slug(t)}`}>{t}</a></li>
          ))}
        </ul>
      </nav>
      <article className="space-y-3 leading-relaxed">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            h1: ({ children }) => <h1 className="text-3xl font-bold">{children}</h1>,
            h2: ({ children }) => (
              <h2 id={slug(text(children))} className="mt-10 scroll-mt-4 border-b border-slate-200 pb-1 text-2xl font-semibold dark:border-slate-800">{children}</h2>
            ),
            h3: ({ children }) => <h3 className="mt-6 text-lg font-semibold">{children}</h3>,
            h4: ({ children }) => <h4 className="mt-4 font-semibold">{children}</h4>,
            ul: ({ children }) => <ul className="list-disc space-y-1 pl-6">{children}</ul>,
            ol: ({ children }) => <ol className="list-decimal space-y-1 pl-6">{children}</ol>,
            a: ({ href, children }) => <a href={href} className="text-indigo-600 underline dark:text-indigo-300">{children}</a>,
            code: ({ children }) => <code className="rounded bg-slate-200 px-1 py-0.5 text-[0.9em] dark:bg-slate-800">{children}</code>,
            pre: ({ children }) => <pre className="overflow-x-auto rounded bg-slate-100 p-3 text-sm dark:bg-slate-900">{children}</pre>,
            blockquote: ({ children }) => <blockquote className="border-l-4 border-indigo-400 bg-indigo-50 p-3 text-sm dark:bg-indigo-950">{children}</blockquote>,
            table: ({ children }) => <div className="overflow-x-auto"><table className="w-full text-sm">{children}</table></div>,
            th: ({ children }) => <th className="border-b border-slate-300 p-1.5 text-left dark:border-slate-700">{children}</th>,
            td: ({ children }) => <td className="border-b border-slate-200 p-1.5 align-top dark:border-slate-800">{children}</td>,
          }}
        >
          {md}
        </ReactMarkdown>
      </article>
    </div>
  );
}
