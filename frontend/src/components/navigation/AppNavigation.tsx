"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Fragment, useEffect, useRef, useState } from "react";

export interface NavigationCounts {
  readonly cases?: number;
  readonly attention?: number;
}

export const NAVIGATION_ITEMS = [
  { href: "/cases", label: "Incidents", icon: "⊙", section: "Monitor" },
  { href: "/services", label: "Services", icon: "◌", section: "Monitor" },
  { href: "/reviews", label: "Review queue", icon: "↗", section: "Respond" },
  { href: "/runs", label: "Run history", icon: "⌁", section: "Respond" },
  { href: "/audit", label: "Audit trace", icon: "≡", section: "Manage" },
] as const;

export function isNavItemActive(pathname: string, href: string): boolean {
  return pathname === href || (href === "/cases" && pathname.startsWith("/cases/"));
}

export function AppNavigation({ tenantId, counts = {} }: { tenantId: string; counts?: NavigationCounts }) {
  const pathname = usePathname() ?? "/cases";
  const [mobileOpen, setMobileOpen] = useState(false);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!mobileOpen) return undefined;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setMobileOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.requestAnimationFrame(() => closeButtonRef.current?.focus());
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [mobileOpen]);

  function closeMobileNavigation() {
    setMobileOpen(false);
    triggerRef.current?.focus();
  }

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="mobile-nav-trigger"
        aria-label="Open navigation"
        aria-expanded={mobileOpen}
        aria-controls="application-navigation"
        onClick={() => setMobileOpen(true)}
      >
        <span aria-hidden="true">☰</span>
      </button>
      {mobileOpen ? <button type="button" className="nav-scrim" aria-label="Dismiss navigation overlay" onClick={closeMobileNavigation} /> : null}
      <aside className={mobileOpen ? "nav-rail nav-rail--mobile-open" : "nav-rail"} aria-label="Application navigation">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">R</span>
          <span className="brand-word">RECLAIM</span>
          <span className="brand-product">Operations</span>
          <button ref={closeButtonRef} type="button" className="mobile-nav-close" aria-label="Close navigation" onClick={closeMobileNavigation}>×</button>
        </div>
        <nav id="application-navigation" className="nav-links" aria-label="Application navigation" data-mobile-open={String(mobileOpen)}>
          {NAVIGATION_ITEMS.map((item, index) => {
            const active = isNavItemActive(pathname, item.href);
            const count = item.href === "/cases" ? counts.cases : item.href === "/reviews" ? counts.attention : undefined;
            return (
              <Fragment key={item.href}>
                {(index === 0 || NAVIGATION_ITEMS[index - 1]?.section !== item.section) ? <span className="nav-section-label">{item.section}</span> : null}
                <Link
                  className={active ? "nav-link nav-link--active" : "nav-link"}
                  href={item.href}
                  aria-label={item.label}
                  aria-current={active ? "page" : undefined}
                  onClick={() => { if (mobileOpen) closeMobileNavigation(); }}
                >
                  <span className="nav-icon" aria-hidden="true">{item.icon}</span>
                  <span>{item.label}</span>
                  {count !== undefined ? <span className={item.href === "/reviews" && count > 0 ? "nav-count nav-count--attention" : "nav-count"}>{count || "—"}</span> : null}
                </Link>
              </Fragment>
            );
          })}
        </nav>
        <div className="nav-footer">
          <span className="nav-footer__label">Connected as</span>
          <span className="nav-footer__operator">
            <span className="operator-avatar">RO</span>
            <span><strong>Reviewer</strong><small>Read-only session</small></span>
          </span>
          <span className="mono nav-tenant-id">{tenantId}</span>
        </div>
      </aside>
    </>
  );
}
