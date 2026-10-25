import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: "Bond Atlas · Curve e titoli sovrani", description:"Curve dei rendimenti e selezione dei singoli titoli governativi in euro, con ISIN, duration e scenari di rischio di tasso.",icons:{icon:"/favicon.svg",shortcut:"/favicon.svg"}};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="it"><body>{children}</body></html>}
