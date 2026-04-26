import type { Metadata } from "next";
import { ClientToaster } from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "S.A.M — Smart Administrative Messenger",
  description:
    "Single point of contact for faculty scheduling. Drive meetings, broadcasts, and calendar work in natural language.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-sans antialiased">
        {children}
        <ClientToaster />
      </body>
    </html>
  );
}
