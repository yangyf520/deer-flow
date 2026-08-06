import { cookies } from "next/headers";
import { Suspense } from "react";
import { Toaster } from "sonner";

import { QueryClientProvider } from "@/components/query-client-provider";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { CommandPalette } from "@/components/workspace/command-palette";
import { GatewayOfflineBanner } from "@/components/workspace/gateway-offline-banner";
import { SettingsDialogHost } from "@/components/workspace/settings";
import { AppSidebar } from "@/components/workspace/shell";
import { WorkspaceSettingsDeepLink } from "@/components/workspace/workspace-settings-deep-link";

function parseSidebarOpenCookie(
  value: string | undefined,
): boolean | undefined {
  if (value === "true") return true;
  if (value === "false") return false;
  return undefined;
}

export async function WorkspaceContent({
  children,
  gatewayUnavailable = false,
}: Readonly<{
  children: React.ReactNode;
  gatewayUnavailable?: boolean;
}>) {
  const cookieStore = await cookies();
  const initialSidebarOpen = parseSidebarOpenCookie(
    cookieStore.get("sidebar_state")?.value,
  );

  return (
    <QueryClientProvider>
      <SidebarProvider className="h-screen" defaultOpen={initialSidebarOpen}>
        <AppSidebar />
        <SidebarInset className="workspace-shell flex min-w-0 flex-col">
          <GatewayOfflineBanner gatewayUnavailable={gatewayUnavailable} />
          {children}
        </SidebarInset>
      </SidebarProvider>
      <CommandPalette />
      <SettingsDialogHost />
      <Suspense fallback={null}>
        <WorkspaceSettingsDeepLink />
      </Suspense>
      <Toaster position="top-center" />
    </QueryClientProvider>
  );
}
