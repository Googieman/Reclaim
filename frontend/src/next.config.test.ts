import { afterEach, describe, expect, it, vi } from "vitest";

async function readApiDestination(environmentValue?: string) {
  if (environmentValue === undefined) delete process.env.RECLAIM_API_INTERNAL_BASE_URL;
  else process.env.RECLAIM_API_INTERNAL_BASE_URL = environmentValue;
  vi.resetModules();
  // @ts-expect-error Next config is an untyped ESM configuration module.
  const config = (await import("../next.config.mjs")).default as {
    rewrites: () => Promise<Array<{ destination: string }>>;
  };
  const rewrites = await config.rewrites();
  return rewrites[0]?.destination;
}

describe("Next API proxy target", () => {
  const original = process.env.RECLAIM_API_INTERNAL_BASE_URL;

  afterEach(() => {
    if (original === undefined) delete process.env.RECLAIM_API_INTERNAL_BASE_URL;
    else process.env.RECLAIM_API_INTERNAL_BASE_URL = original;
  });

  it("uses loopback when Next runs directly on the local machine", async () => {
    await expect(readApiDestination()).resolves.toBe("http://127.0.0.1:8000/tenants/:path*");
  });

  it("keeps the Docker service-name override intact", async () => {
    await expect(readApiDestination("http://api:8000")).resolves.toBe("http://api:8000/tenants/:path*");
  });
});
