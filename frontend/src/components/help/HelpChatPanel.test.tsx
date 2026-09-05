import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { HelpChatPanel } from "./HelpChatPanel";

describe("HelpChatPanel", () => {
  it("renders a compact floating trigger while closed", () => {
    const markup = renderToStaticMarkup(<HelpChatPanel tenantId="tenant-1" />);

    expect(markup).toContain('class="help-chat__trigger help-chat__trigger--floating"');
    expect(markup).toContain('aria-label="Open documentation help"');
    expect(markup).not.toContain('role="dialog"');
  });

  it("keeps the bounded question form when open", () => {
    const markup = renderToStaticMarkup(<HelpChatPanel tenantId="tenant-1" initialOpen />);

    expect(markup).toContain('role="dialog"');
    expect(markup).toContain('aria-label="Documentation help"');
    expect(markup).toContain('aria-label="Documentation question"');
    expect(markup).toContain('type="submit"');
    expect(markup).not.toContain("dangerouslySetInnerHTML");
  });
});
