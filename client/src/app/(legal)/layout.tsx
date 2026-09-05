import "../globals.css";
import Link from "next/link";
import { Toaster } from "@/components/ui/sonner";
import { fontVariables } from "@/app/fonts";

export default function LegalLayout({
    children,
}: {
    children: React.ReactNode;
}) {
    return (
        <html lang="en" suppressHydrationWarning>
            <head>
                <script
                    dangerouslySetInnerHTML={{
                        __html: `
(function() {
  try {
    var darkMode = localStorage.getItem('darkMode');
    if (darkMode === 'dark' || (!darkMode && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  } catch (e) {}
})();
                        `
                    }}
                    id="theme-script"
                />
            </head>
            <body className={`${fontVariables} antialiased`}>
                <main className="container mx-auto py-8">
                    <Link href="/" className="flex items-center justify-center mb-8">
                        <span className="text-2xl font-bold">Scholens</span>
                    </Link>
                    <div className="mx-2 md:mx-auto max-w-3xl pb-10 prose prose-headings:mt-8 prose-headings:font-semibold prose-h1:text-5xl prose-h2:text-4xl prose-h3:text-3xl prose-h4:text-2xl prose-h5:text-xl prose-h6:text-lg dark:prose-invert">
                        {children}
                    </div>
                </main>
                <Toaster />
            </body>
        </html>
    );
}
