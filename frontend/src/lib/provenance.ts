/** Client-visible build provenance; no secrets, evidence, or credentials. */

export interface FrontendProvenance {
  readonly version: string;
  readonly commitSha: string;
}

export const frontendProvenance: FrontendProvenance = {
  version: process.env.NEXT_PUBLIC_BUILD_VERSION ?? "unversioned",
  commitSha: process.env.NEXT_PUBLIC_COMMIT_SHA ?? "unknown",
};
