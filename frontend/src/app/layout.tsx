import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "BedSynth AI | Hospital Operations Studio",
  description: "A workspace for synthetic hospital operations data workflows.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <a className="skip-link sr-only focus:not-sr-only" href="#main-content">Skip to content</a>
        {children}
      </body>
    </html>
  );
}
