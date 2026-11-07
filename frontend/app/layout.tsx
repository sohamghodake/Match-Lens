import type { Metadata } from "next";
import Link from "next/link";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "MatchLens",
  description: "Ranked remote jobs and an ATS score from your resume",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
        <nav className="mx-auto flex w-full max-w-2xl items-center justify-between px-4 pt-5 text-sm">
          <Link href="/" className="font-semibold tracking-tight">
            MatchLens
          </Link>
          <Link href="/status" className="text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100">
            Status
          </Link>
        </nav>
        {children}
        <footer className="mx-auto w-full max-w-2xl px-4 pb-8 pt-4 text-xs text-zinc-500">
          Jobs from{" "}
          <a href="https://remotive.com" className="underline">Remotive</a>,{" "}
          <a href="https://remoteok.com" className="underline">Remote OK</a> and company
          Greenhouse boards; every job links to its original listing. Uploaded resumes are
          deleted after 24 hours.{" "}
          <a href="https://github.com/sohamghodake/Match-Lens" className="underline">Source on GitHub</a>
        </footer>
      </body>
    </html>
  );
}
