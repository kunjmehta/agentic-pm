/**
 * GET /api/sandbox/files?daytonaSandboxId=...&workDir=...
 * List Python files in the sandbox src/ directory via Daytona TypeScript SDK.
 * Uses process.executeCommand (find) — same as the Python backend, but server-side TS.
 */

import { NextRequest, NextResponse } from 'next/server';
import { Daytona } from '@daytonaio/sdk';
import { readFileSync } from 'fs';
import { join } from 'path';

function getDaytonaApiKey(): string {
  try {
    const secretPath = join(process.cwd(), '..', 'config', 'secret.json');
    const parsed = JSON.parse(readFileSync(secretPath, 'utf-8')) as Record<string, unknown>;
    const nested = parsed?.daytona as Record<string, unknown> | undefined;
    return (nested?.api_key ?? parsed?.['daytona.api_key'] ?? '') as string;
  } catch (e) {
    console.error('[sandbox/files] failed to read secret.json:', e);
    return '';
  }
}

export async function GET(req: NextRequest) {
  const daytonaSandboxId = req.nextUrl.searchParams.get('daytonaSandboxId');
  const workDir = req.nextUrl.searchParams.get('workDir');

  if (!daytonaSandboxId || !workDir) {
    return NextResponse.json({ error: 'Missing daytonaSandboxId or workDir' }, { status: 400 });
  }

  const apiKey = getDaytonaApiKey();
  if (!apiKey) {
    return NextResponse.json({ error: 'daytona.api_key not found in secret.json' }, { status: 500 });
  }

  try {
    const daytona = new Daytona({ apiKey });
    const sandbox = await daytona.get(daytonaSandboxId);

    // Use find command — proven to work, same as Python backend
    const res = await sandbox.process.executeCommand(
      `find ${workDir}/src -name '*.py' 2>/dev/null | sort`,
      undefined,
      undefined,
      30,
    );

    const files = (res.result ?? '')
      .split('\n')
      .map((l: string) => l.trim())
      .filter(Boolean)
      .map((f: string) =>
        f.startsWith(workDir + '/') ? f.slice(workDir.length + 1) : f,
      );

    return NextResponse.json({ files });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error('[sandbox/files] error:', msg);
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
