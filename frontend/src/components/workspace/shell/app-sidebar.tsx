"use client";

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarRail,
} from "@/components/ui/sidebar";

import { WorkspaceChannelsList } from "../channels/workspace-channels-list";
import { WorkspaceNavChatList } from "../workspace-nav-chat-list";
import { WorkspaceNavMenu } from "../workspace-nav-menu";

import { SidebarHead } from "./sidebar-head";

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  return (
    <>
      <Sidebar variant="sidebar" collapsible="icon" {...props}>
        <SidebarHeader className="py-0">
          <SidebarHead />
        </SidebarHeader>
        <SidebarContent>
          <WorkspaceNavChatList />
          <WorkspaceChannelsList />
        </SidebarContent>
        <SidebarFooter>
          <WorkspaceNavMenu />
        </SidebarFooter>
        <SidebarRail />
      </Sidebar>
    </>
  );
}
