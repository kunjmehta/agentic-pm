'use client';

/**
 * /sandbox — full-tab VS Code redirect.
 * Reads `url` query param and navigates directly to the Daytona preview URL
 * so auth0 runs in a top-level browser context (no iframe restrictions).
 */

import { useEffect, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';

function Redirect() {
  const params = useSearchParams();
  const url = params.get('url');

  useEffect(() => {
    if (url) window.location.replace(url);
  }, [url]);

  if (!url) {
    return (
      <div className="sandbox-redirect-error">
        <p>No VS Code URL provided.</p>
      </div>
    );
  }

  return (
    <div className="sandbox-redirect-loading">
      <div className="sandbox-spinner" />
      <p>Opening VS Code…</p>
    </div>
  );
}

export default function SandboxPage() {
  return (
    <Suspense fallback={<div className="sandbox-redirect-loading"><div className="sandbox-spinner" /></div>}>
      <Redirect />
    </Suspense>
  );
}
