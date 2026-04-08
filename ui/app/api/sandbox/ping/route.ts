/**
 * GET /api/sandbox/ping?daytonaSandboxId=...
 * Diagnostic: tests API key reading and Daytona SDK connection.
 */

import { NextRequest, NextResponse } from 'next/server';
import { Daytona } from '@daytonaio/sdk';
import { readFileSync } from 'fs';
import { join } from 'path';

export async function GET(req: NextRequest) {
  const sandboxId = req.nextUrl.searchParams.get('daytonaSandboxId') ?? '';

  // Step 1: Read API key
  let apiKey = '';
  let secretError = '';
  try {
    const secretPath = join(process.cwd(), '..', 'config', 'secret.json');
    const parsed = JSON.parse(readFileSync(secretPath, 'utf-8')) as Record<string, unknown>;
    const nested = parsed?.daytona as Record<string, unknown> | undefined;
    apiKey = (nested?.api_key ?? parsed?.['daytona.api_key'] ?? '') as string;
  } catch (e) {
    secretError = String(e);
  }

  if (!apiKey) {
    return NextResponse.json({
      ok: false,
      step: 'read_secret',
      error: secretError || 'daytona.api_key empty',
      cwd: process.cwd(),
    });
  }

  // Step 2: Connect to Daytona
  if (!sandboxId) {
    return NextResponse.json({ ok: true, step: 'api_key_ok', keyLength: apiKey.length });
  }

  try {
    const daytona = new Daytona({ apiKey });
    const sandbox = await daytona.get(sandboxId);
    return NextResponse.json({
      ok: true,
      step: 'sandbox_fetched',
      sandboxName: (sandbox as { name?: string }).name,
      sandboxId,
    });
  } catch (e) {
    return NextResponse.json({ ok: false, step: 'daytona_get', error: String(e) });
  }
}
