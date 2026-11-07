import type { Metadata } from "next";
import AppShell from "@/components/AppShell";
import "./globals.css";

export const metadata: Metadata = {
  title: "SENTINAL Control Center",
  description: "Local read-only dashboard for SENTINAL AI: device inventory, monitoring and activity history.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full bg-page text-ink">
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
