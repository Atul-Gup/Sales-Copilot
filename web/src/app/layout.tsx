import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { BottomNav } from "@/components/BottomNav";
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
  description: "Objection handling and comparisons for the Volvo showroom floor.",
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
      <body className="flex min-h-full flex-col">
        {/* pb-16 reserves space for the fixed BottomNav so page content is
            never rendered underneath it. */}
        <main className="flex-1 pb-16">{children}</main>
        <BottomNav />
      </body>
    </html>
  );
}
