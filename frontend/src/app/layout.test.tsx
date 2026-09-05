import type { ReactElement } from "react";
import { describe, expect, it } from "vitest";
import RootLayout from "./layout";

describe("root layout", () => {
  it("suppresses attribute-only hydration noise from browser extensions", () => {
    const documentTree = RootLayout({ children: "content" }) as ReactElement<{
      children: ReactElement<{ suppressHydrationWarning?: boolean }>;
    }>;
    const body = documentTree.props.children;

    expect(body.type).toBe("body");
    expect(body.props.suppressHydrationWarning).toBe(true);
  });
});
