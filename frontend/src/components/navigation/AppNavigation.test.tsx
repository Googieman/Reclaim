import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { AppNavigation } from "./AppNavigation";

vi.mock("next/navigation", () => ({
  usePathname: () => "/cases",
}));

describe("AppNavigation", () => {
  it("mounts the help chat outside the transformed navigation rail", () => {
    const markup = renderToStaticMarkup(<AppNavigation tenantId="tenant-1" />);
    const navRail = markup.match(/<aside[\s\S]*?<\/aside>/)?.[0];

    expect(navRail).toBeDefined();
    expect(navRail).not.toContain("help-chat");
    expect(markup).toContain('class="help-chat"');
  });
});
