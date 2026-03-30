import type { Metadata } from "next";
import "./globals.css";
import ToastContainer from "@/components/ToastContainer";
import { ThemeProvider } from "@/components/ThemeProvider";

export const metadata: Metadata = {
  title: "Domain Monitor — AI Industry Intelligence",
  description: "AI-powered real-time industry monitoring dashboard",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className="h-full antialiased"
    >
      <body className="h-full">
        <ThemeProvider attribute="data-theme" defaultTheme="system" enableSystem>
          {children}
          <ToastContainer />
        </ThemeProvider>
      </body>
    </html>
  );
}
