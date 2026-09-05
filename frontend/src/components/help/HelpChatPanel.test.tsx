import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { HelpChatPanel } from "./HelpChatPanel";

const globalsCss = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "../../app/globals.css"), "utf8");

function zIndexFor(selector: string): number {
  const rule = globalsCss.split(/\r?\n/).find((line) => line.startsWith(`${selector} {`));
  return Number(rule?.match(/z-index:\s*(\d+)/)?.[1]);
}

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

  it("keeps the help widget below navigation and modal overlays", () => {
    expect(zIndexFor(".help-chat")).toBeLessThan(50);
    expect(zIndexFor(".help-chat__trigger--floating")).toBeLessThan(50);
    expect(zIndexFor(".help-chat__panel")).toBeLessThan(50);
  });
});
