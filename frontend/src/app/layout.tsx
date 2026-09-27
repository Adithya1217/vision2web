import type { Metadata, Viewport } from "next";
import { DM_Sans, IBM_Plex_Mono, Press_Start_2P } from "next/font/google";

import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "Dukaan Desk — MSME business dashboard",
  description: "Inventory, invoicing, khata, purchasing and GST reports for small businesses.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

const sans = DM_Sans({ subsets: ["latin"], variable: "--font-dm-sans" });
const mono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-plex-mono" });
const pixel = Press_Start_2P({ subsets: ["latin"], weight: "400", variable: "--font-press-start" });

const themeScript = `try{var t=localStorage.getItem("msme.theme");if(t==="dark"||t==="light")document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning className={`${sans.variable} ${mono.variable} ${pixel.variable}`}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
