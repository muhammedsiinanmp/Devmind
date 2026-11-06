import { describe, expect, it } from "vitest";
import { repositoriesApi } from "./repositories";

// The regex repository scan was removed (issue #75).
describe("repository scan removal", () => {
  it("has no scan page or scan API module", () => {
    const modules = Object.keys(
      import.meta.glob(["../pages/ScanReport.tsx", "./scan.ts"]),
    );
    expect(modules).toEqual([]);
  });

  it("does not expose a scan trigger on the repositories API", () => {
    expect("triggerScan" in repositoriesApi).toBe(false);
  });
});
