import { describe, expect, it } from "vitest";

import { isWorkspaceSection, workspaceSections } from "./workspace-sections";

describe("workspace sections", () => {
  it("accepts every routed workspace and rejects unknown paths", () => {
    expect(workspaceSections).toHaveLength(8);
    for (const section of workspaceSections) expect(isWorkspaceSection(section)).toBe(true);
    expect(isWorkspaceSection("everything-on-one-page")).toBe(false);
  });
});
