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
      </body>
    </html>
  );
}
