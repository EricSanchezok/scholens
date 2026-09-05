import type { Metadata } from "next";
import "../globals.css";
import { fontVariables } from "@/app/fonts";
import { AppSidebar } from "@/components/sidebar/AppSidebar";
import { AppHeader } from "@/components/AppHeader";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { AuthProvider } from "@/lib/auth";

import { Toaster } from "@/components/ui/sonner";
import { PostHogProvider, ThemeProvider } from "@/lib/providers";
import { SidebarController } from "@/components/utils/SidebarAutoCollapse";

export const metadata: Metadata = {
	metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || "http://127.0.0.1:7303"),
	title: "Scholens",
	description: "Legacy Scholens comparison client.",
	openGraph: {
		title: "Scholens",
		description: "Legacy Scholens comparison client.",
		type: "website",
	},
	twitter: {
		card: "summary",
		title: "Scholens",
		description: "Legacy Scholens comparison client.",
	},
};

export default function RootLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {
	return (
		<html lang="en" suppressHydrationWarning>
			<head>
				<script
					id="theme-script"
					dangerouslySetInnerHTML={{
						__html: `
      try {
        if (localStorage.getItem('darkMode') === 'dark' ||
            (!localStorage.getItem('darkMode') && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
          document.documentElement.classList.add('dark');
        } else {
          document.documentElement.classList.remove('dark');
        }
      } catch (e) {}
    `,
					}}
				/>
			</head>
			<body
				className={`${fontVariables} antialiased`}
			>
				<ThemeProvider>
					<AuthProvider>
						<PostHogProvider>
							<SidebarProvider>
								<AppSidebar />
								<SidebarInset>
									<AppHeader />
									<SidebarController>
										{children}
									</SidebarController>
								</SidebarInset>
							</SidebarProvider>
						</PostHogProvider>
					</AuthProvider>
				</ThemeProvider>
				<Toaster
					position="top-right"
					richColors
					duration={3000}
				/>
			</body>
		</html>
	);
}
