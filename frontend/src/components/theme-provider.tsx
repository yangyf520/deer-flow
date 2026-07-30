"use client";

import { usePathname } from "next/navigation";
import { ThemeProvider as NextThemesProvider } from "next-themes";

// next-themes injects an inline <script> to avoid theme flash. React 19 warns when
// that script is rendered again on the client; SSR still emits a runnable script.
const clientScriptProps =
  typeof window === "undefined"
    ? undefined
    : ({ type: "application/json" } as const);

export function ThemeProvider({
  children,
  ...props
}: React.ComponentProps<typeof NextThemesProvider>) {
  const pathname = usePathname();
  return (
    <NextThemesProvider
      {...props}
      scriptProps={clientScriptProps}
      forcedTheme={pathname === "/" ? "dark" : undefined}
    >
      {children}
    </NextThemesProvider>
  );
}
