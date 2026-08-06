import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

// Issue #3482: the /workspace/chats list page used to stop at the first 50
// threads with no way to load more. `useInfiniteThreads()` + a sentinel near
// the bottom of the list now pages through the backend.

const TOTAL_THREADS = 120;
const PAGE_SIZE = 50;

const THREADS = Array.from({ length: TOTAL_THREADS }, (_, i) => {
  // Pad index so titles sort deterministically as strings. Keep updated_at
  // monotonically descending to match the backend's updated_at-desc search
  // order, so paging boundaries are stable across runs.
  const index = String(i + 1).padStart(3, "0");
  return {
    thread_id: `00000000-0000-0000-0000-0000000${index.padStart(5, "0")}`,
    title: `Conversation ${index}`,
    updated_at: new Date(
      Date.UTC(2025, 5, 30, 12, 0, 0) - i * 60_000,
    ).toISOString(),
  };
});

const FIRST_PAGE_LAST = `Conversation ${String(PAGE_SIZE).padStart(3, "0")}`;
const SECOND_PAGE_FIRST = `Conversation ${String(PAGE_SIZE + 1).padStart(3, "0")}`;

test.describe("Thread list infinite scroll (issue #3482)", () => {
  test("chats list page loads more threads when scrolling to the bottom", async ({
    page,
  }) => {
    mockLangGraphAPI(page, { threads: THREADS });

    await page.goto("/workspace/chats");

    const main = page.locator("main");

    // First page renders.
    await expect(main.getByText(FIRST_PAGE_LAST)).toBeVisible({
      timeout: 15_000,
    });
    // Items past the first page have not been fetched yet.
    await expect(main.getByText(SECOND_PAGE_FIRST)).toHaveCount(0);

    // Scrolling the sentinel into view triggers the next page.
    const sentinel = page.getByTestId("chats-page-sentinel");
    await sentinel.scrollIntoViewIfNeeded();

    await expect(main.getByText(SECOND_PAGE_FIRST)).toBeVisible({
      timeout: 15_000,
    });
  });

  test("chats list auto-paginates while a search filter is active", async ({
    page,
  }) => {
    let searchRequestCount = 0;
    page.on("request", (request) => {
      if (request.url().includes("/api/langgraph/threads/search")) {
        searchRequestCount += 1;
      }
    });

    mockLangGraphAPI(page, { threads: THREADS });

    await page.goto("/workspace/chats");

    await expect(page.locator("main").getByText(FIRST_PAGE_LAST)).toBeVisible({
      timeout: 15_000,
    });
    const baselineRequests = searchRequestCount;

    await page
      .getByPlaceholder("Search chats")
      .fill("zzz-no-such-conversation");

    await expect(page.getByTestId("chats-page-load-more")).toHaveCount(0);
    await expect(page.getByTestId("chats-page-sentinel")).toBeVisible();

    await page.getByTestId("chats-page-sentinel").scrollIntoViewIfNeeded();

    await expect
      .poll(() => searchRequestCount, { timeout: 10_000 })
      .toBeGreaterThan(baselineRequests);
  });
});
