import { describe, expect, it } from "@rstest/core";

import { itemRowStatusToneFromValue } from "@/components/component/item";

describe("itemRowStatusToneFromValue", () => {
  it("maps healthy lifecycle states to success", () => {
    expect(itemRowStatusToneFromValue("ready")).toBe("success");
    expect(itemRowStatusToneFromValue("enabled")).toBe("success");
    expect(itemRowStatusToneFromValue("completed")).toBe("success");
  });

  it("maps in-progress states to warning", () => {
    expect(itemRowStatusToneFromValue("processing")).toBe("warning");
    expect(itemRowStatusToneFromValue("queued")).toBe("warning");
    expect(itemRowStatusToneFromValue("running")).toBe("warning");
    expect(itemRowStatusToneFromValue("paused")).toBe("warning");
  });

  it("maps failure states to danger", () => {
    expect(itemRowStatusToneFromValue("failed")).toBe("danger");
    expect(itemRowStatusToneFromValue("error")).toBe("danger");
  });

  it("falls back to neutral for unknown values", () => {
    expect(itemRowStatusToneFromValue("skipped")).toBe("neutral");
    expect(itemRowStatusToneFromValue("")).toBe("neutral");
  });
});
