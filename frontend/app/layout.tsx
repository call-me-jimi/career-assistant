import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Personal Application Assistant",
  description: "Agentic, conversational cover letter and Q&A assistant.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">{children}</body>
    </html>
  );
}
