"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Separator } from "@/components/ui/separator";

// The app-shell header. Hidden inside a project workspace — the workspace's
// own breadcrumb bar carries the sidebar trigger there, keeping chrome to a
// single compact bar. (/projects and /projects/create are not workspaces.)
export function AppHeader() {
    const pathname = usePathname();
    const isProjectWorkspace = /^\/projects\/[^/]+/.test(pathname) && !pathname.startsWith("/projects/create");
    if (isProjectWorkspace) return null;

    return (
        <header className="flex h-12 shrink-0 items-center gap-2 border-b px-4">
            <SidebarTrigger className="-ml-1" />
            <Separator orientation="vertical" className="mr-2 h-4" />
            <Link href="/" className="flex flex-1 items-center hover:opacity-80 transition-opacity">
                <span className="text-sm font-semibold">Scholens</span>
            </Link>
        </header>
    );
}
