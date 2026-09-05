import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { HelpChatPanel } from "./HelpChatPanel";

describe("HelpChatPanel", () => {
  it("exposes a keyboard-friendly advisory help entry point", () => {
    const markup = renderToStaticMarkup(<HelpChatPanel tenantId="tenant-1" />);

    expect(markup).toContain('aria-label="Open documentation help"');
    expect(markup).toContain("Documentation help");
    expect(markup).toContain("Advisory only");
  });

  it("renders the bounded question form without an HTML injection sink", () => {
    const markup = renderToStaticMarkup(<HelpChatPanel tenantId="tenant-1" initialOpen />);

    expect(markup).toContain('aria-label="Documentation help"');
    expect(markup).toContain('aria-label="Documentation question"');
    expect(markup).toContain('type="submit"');
    expect(markup).not.toContain("dangerouslySetInnerHTML");
  });
});
