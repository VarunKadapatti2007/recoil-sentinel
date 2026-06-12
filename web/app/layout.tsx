import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import { VersionProvider } from "@/components/version-context";
import { Shell } from "@/components/shell";

export const metadata: Metadata = {
  title: "Recoil — CI/CD for AI agents",
  description: "Regression-eval harness and publish gate for AI agents.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-bg text-text-1">
        <VersionProvider>
          <Shell>{children}</Shell>
        </VersionProvider>
      </body>
    </html>
  );
}
