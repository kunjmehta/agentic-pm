/**
 * GET  /api/sandbox/file?daytonaSandboxId=...&workDir=...&path=src/...
 * PUT  /api/sandbox/file  body: {daytonaSandboxId, workDir, path, content}
 *
 * Read / write a sandbox file via Daytona TypeScript SDK.
 * Runs server-side in Next.js (Node.js) — API key never reaches the browser.
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
    console.error('[sandbox/file] failed to read secret.json:', e);
    return '';
  }
}

export async function GET(req: NextRequest) {
  const daytonaSandboxId = req.nextUrl.searchParams.get('daytonaSandboxId');
  const workDir = req.nextUrl.searchParams.get('workDir');
  const filePath = req.nextUrl.searchParams.get('path');

  if (!daytonaSandboxId || !workDir || !filePath) {
    return NextResponse.json({ error: 'Missing params' }, { status: 400 });
  }

  const apiKey = getDaytonaApiKey();
  if (!apiKey) {
    return NextResponse.json({ error: 'daytona.api_key not found in secret.json' }, { status: 500 });
  }

  try {
    const daytona = new Daytona({ apiKey });
    const sandbox = await daytona.get(daytonaSandboxId);
    const buffer = await sandbox.fs.downloadFile(`${workDir}/${filePath}`);
    const content = buffer.toString('utf-8');
    return NextResponse.json({ path: filePath, content });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error('[sandbox/file GET] error:', msg);
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}

export async function PUT(req: NextRequest) {
  let body: { daytonaSandboxId?: string; workDir?: string; path?: string; content?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON body' }, { status: 400 });
  }

  const { daytonaSandboxId, workDir, path: filePath, content } = body;
  if (!daytonaSandboxId || !workDir || !filePath || content === undefined) {
    return NextResponse.json({ error: 'Missing fields' }, { status: 400 });
  }

  const apiKey = getDaytonaApiKey();
  if (!apiKey) {
    return NextResponse.json({ error: 'daytona.api_key not found in secret.json' }, { status: 500 });
  }

  try {
    const daytona = new Daytona({ apiKey });
    const sandbox = await daytona.get(daytonaSandboxId);
    await sandbox.fs.uploadFile(Buffer.from(content, 'utf-8'), `${workDir}/${filePath}`);
    return NextResponse.json({ ok: true, path: filePath });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error('[sandbox/file PUT] error:', msg);
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
