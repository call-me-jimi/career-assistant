import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Personal Career Assistant",
  description: "Agentic career helper: cover letters, interview prep, and career advice.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">{children}</body>
    </html>
  );
}
