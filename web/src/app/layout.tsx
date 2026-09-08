import type { Metadata, Viewport } from "next";
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
  title: "Showroom Copilot",
  description: "Grounded specs, comparisons, and objection handling for the Volvo showroom floor.",
};

// width=device-width + initial-scale=1 is the baseline for a mobile-first
// layout; maximumScale is left unset so a consultant can still pinch-zoom a
// spec table if they need to — a locked zoom is an accessibility regression,
// not a mobile optimisation.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="flex h-full flex-col">{children}</body>
    </html>
  );
}
