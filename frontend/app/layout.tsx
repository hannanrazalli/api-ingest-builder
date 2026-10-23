import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: "API Ingest Builder", description: "Deterministic ingestion tools for data engineers" };
export default function Layout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}
