import { cookies } from "next/headers";

import { isStaticWebsiteOnly } from "../static-mode";

import { AUTH_DISABLED_USER, isAuthDisabledMode } from "./auth-disabled-user";
import { AUTH_REQUEST_TIMEOUT_MS } from "./constants";
import { getGatewayConfig } from "./gateway-config";
import { STATIC_WEBSITE_USER } from "./static-user";
import { type AuthResult, userSchema } from "./types";

function isAuthFetchAbortError(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === "AbortError") ||
    (typeof error === "object" &&
      error !== null &&
      Reflect.get(error, "name") === "AbortError")
  );
}

async function fetchWithTimeout(
  input: string,
  init: RequestInit = {},
): Promise<Response> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), AUTH_REQUEST_TIMEOUT_MS);
  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timeout);
  }
}

/**
 * Fetch the authenticated user from the gateway using the request's cookies.
 * Returns a tagged AuthResult — callers use exhaustive switch, no try/catch.
 */
export async function getServerSideUser(): Promise<AuthResult> {
  if (isStaticWebsiteOnly()) {
    return {
      tag: "authenticated",
      user: STATIC_WEBSITE_USER,
    };
  }

  if (isAuthDisabledMode()) {
    return {
      tag: "authenticated",
      user: AUTH_DISABLED_USER,
    };
  }

  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get("access_token");

  let internalGatewayUrl: string;
  try {
    internalGatewayUrl = getGatewayConfig().internalGatewayUrl;
  } catch (err) {
    return { tag: "config_error", message: String(err) };
  }

  if (!sessionCookie) {
    try {
      const setupRes = await fetchWithTimeout(
        `${internalGatewayUrl}/api/v1/auth/setup-status`,
        { cache: "no-store" },
      );
      if (setupRes.ok) {
        const setupData = (await setupRes.json()) as { needs_setup?: boolean };
        if (setupData.needs_setup) {
          return { tag: "system_setup_required" };
        }
      }
    } catch (err) {
      if (!isAuthFetchAbortError(err)) {
        console.warn("[SSR auth] setup-status unreachable:", err);
      }
      // If setup-status is unreachable/times out, fall through to unauthenticated.
    }
    return { tag: "unauthenticated" };
  }

  try {
    const res = await fetchWithTimeout(`${internalGatewayUrl}/api/v1/auth/me`, {
      headers: { Cookie: `access_token=${sessionCookie.value}` },
      cache: "no-store",
    });

    if (res.ok) {
      const parsed = userSchema.safeParse(await res.json());
      if (!parsed.success) {
        console.error("[SSR auth] Malformed /auth/me response:", parsed.error);
        return { tag: "gateway_unavailable" };
      }
      if (parsed.data.needs_setup) {
        return { tag: "needs_setup", user: parsed.data };
      }
      return { tag: "authenticated", user: parsed.data };
    }
    if (res.status === 401 || res.status === 403) {
      return { tag: "unauthenticated" };
    }
    console.error(`[SSR auth] /api/v1/auth/me responded ${res.status}`);
    return { tag: "gateway_unavailable" };
  } catch (err) {
    if (isAuthFetchAbortError(err)) {
      return { tag: "gateway_unavailable" };
    }
    console.error("[SSR auth] Failed to reach gateway:", err);
    return { tag: "gateway_unavailable" };
  }
}
