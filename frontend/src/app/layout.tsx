import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "RECLAIM · Incident command",
  description: "Tenant-scoped incident investigation and verified containment review.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}
