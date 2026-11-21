import type { Metadata } from "next";
import AppShell from "@/components/AppShell";
import "./globals.css";
import "./landing.css";

export const metadata: Metadata = {
  title: "BedSynth AI | Hospital Operations Studio",
  description: "Generate reproducible synthetic hospital operations datasets for research, analytics, simulation, and optimization testing without real patient records.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <a className="skip-link sr-only focus:not-sr-only" href="#main-content">Skip to content</a>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
