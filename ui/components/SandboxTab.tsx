'use client';

/**
 * SandboxTab layout:
 *
 *  ┌─ Toolbar ──────────────────────────────────────────────────────────┐
 *  │ [name]  [VS Code ↗]  [Publish New ▸]  [Publish All ▸]  [✕]       │
 *  └────────────────────────────────────────────────────────────────────┘
 *  ┌─ File Tree (20%) ─┬─ Monaco Editor (45%) ─┬─ Agent Chat (35%) ───┐
 *  │                   │                        │                      │
 *  └───────────────────┴────────────────────────┴──────────────────────┘
 *  ┌─ Terminal (full width, 220px) ───────────────────────────────────┐
 *  └──────────────────────────────────────────────────────────────────┘
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  KeyboardEvent,
  lazy,
  Suspense,
} from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useSandbox, type AgentMessage } from '@/hooks/useSandbox';
import {
  listSandboxFiles,
  readSandboxFile,
  writeSandboxFile,
} from '@/lib/sandboxApi';
import SandboxFileTree from '@/components/SandboxFileTree';

const MonacoEditor = lazy(() => import('@monaco-editor/react'));

interface SandboxTabProps { apiUrl: string }

// ── Overlays ──────────────────────────────────────────────────────────────────

function Overlay({ children }: { children: React.ReactNode }) {
  return <div className="sandbox-full-overlay"><div className="sandbox-overlay">{children}</div></div>;
}

function MessageBubble({ msg }: { msg: AgentMessage }) {
  return (
    <div className={`sandbox-msg sandbox-msg-${msg.role}`}>
      <span className="sandbox-msg-label">{msg.role === 'user' ? 'YOU' : 'AGENT'}</span>
      <pre className="sandbox-msg-body">
        {msg.content}
        {msg.streaming && <span className="sandbox-cursor">▋</span>}
      </pre>
    </div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function SandboxTab({ apiUrl }: SandboxTabProps) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const {
    phase, sandboxId, sandboxName, vsCodeUrl, errorMsg,
    messages, isAgentStreaming,
    daytonaSandboxId, workDir, terminalUrl,
    create, publish, destroy, sendQuery, resumeFrom, lastPublish,
  } = useSandbox(apiUrl);

  // On mount: restore sandbox from URL param
  const didResume = useRef(false);
  useEffect(() => {
    if (didResume.current) return;
    didResume.current = true;
    const id = searchParams.get('sandbox');
    if (id) resumeFrom(id);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Sync URL with sandbox state
  useEffect(() => {
    const current = searchParams.get('sandbox');
    if (phase === 'ready' && sandboxId && current !== sandboxId) {
      const params = new URLSearchParams(searchParams.toString());
      params.set('sandbox', sandboxId);
      router.replace(`?${params.toString()}`);
    } else if ((phase === 'idle' || phase === 'not_found') && current) {
      const params = new URLSearchParams(searchParams.toString());
      params.delete('sandbox');
      router.replace(`?${params.toString()}`);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, sandboxId]);

  const scaffoldPath = sandboxName
    ? `src/server/skills/quant/new_strategy_${sandboxName.replace(/-/g, '_')}.py`
    : '';

  // ── Editor state ──
  const [files, setFiles] = useState<string[]>([]);
  const [activePath, setActivePath] = useState('');
  const [editorContent, setEditorContent] = useState('');
  const [savedContent, setSavedContent] = useState('');
  const [editorLoading, setEditorLoading] = useState(false);
  const [saveStatus, setSaveStatus] = useState<'saved' | 'unsaved' | 'saving'>('saved');

  // ── Chat state ──
  const [chatInput, setChatInput] = useState('');
  const [publishMode, setPublishMode] = useState<'all' | 'new' | null>(null);
  const [destroyConfirm, setDestroyConfirm] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Load file list when ready; auto-open scaffold
  useEffect(() => {
    if (phase !== 'ready' || !daytonaSandboxId || !workDir) return;
    listSandboxFiles(daytonaSandboxId, workDir)
      .then((res) => {
        setFiles(res.files);
        const target = res.files.find((f) => f === scaffoldPath)
          ?? res.files.find((f) => f.includes('new_strategy_'))
          ?? res.files[0]
          ?? '';
        if (target) loadFile(target);
      })
      .catch((err) => {
        setEditorContent(`# Error listing files: ${err?.message ?? err}`);
        setSaveStatus('saved');
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, daytonaSandboxId, workDir]);

  const loadFile = useCallback(async (path: string) => {
    if (!daytonaSandboxId || !workDir) return;
    setEditorLoading(true);
    setActivePath(path);
    try {
      const res = await readSandboxFile(daytonaSandboxId, workDir, path);
      setEditorContent(res.content);
      setSavedContent(res.content);
      setSaveStatus('saved');
    } catch {
      setEditorContent('# Error loading file');
      setSaveStatus('saved');
    } finally {
      setEditorLoading(false);
    }
  }, [daytonaSandboxId, workDir]);

  const saveFile = useCallback(async () => {
    if (!daytonaSandboxId || !workDir || !activePath || saveStatus !== 'unsaved') return;
    setSaveStatus('saving');
    try {
      await writeSandboxFile(daytonaSandboxId, workDir, activePath, editorContent);
      setSavedContent(editorContent);
      setSaveStatus('saved');
    } catch { setSaveStatus('unsaved'); }
  }, [daytonaSandboxId, workDir, activePath, editorContent, saveStatus]);

  useEffect(() => {
    const handler = (e: globalThis.KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); saveFile(); }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [saveFile]);

  // Refresh editor after agent responds
  const prevStreamRef = useRef(false);
  useEffect(() => {
    if (prevStreamRef.current && !isAgentStreaming && sandboxId && activePath) {
      loadFile(activePath);
    }
    prevStreamRef.current = isAgentStreaming;
  }, [isAgentStreaming, sandboxId, activePath, loadFile]);

  const handleChatSend = useCallback(() => {
    const q = chatInput.trim();
    if (!q || isAgentStreaming || phase !== 'ready') return;
    setChatInput('');
    sendQuery(q);
  }, [chatInput, isAgentStreaming, phase, sendQuery]);

  const handleChatKey = useCallback((e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleChatSend(); }
  }, [handleChatSend]);

  const handlePublish = useCallback(async (mode: 'all' | 'new') => {
    if (publishMode === mode) {
      setPublishMode(null);
      await publish(mode);
    } else {
      setPublishMode(mode);
    }
  }, [publishMode, publish]);

  const isLoading = phase === 'creating' || phase === 'publishing' || phase === 'destroying';
  const isDirty = saveStatus === 'unsaved';

  // ── Non-ready states ──
  if (phase === 'idle' || phase === 'not_found' || phase === 'creating' || phase === 'error' || isLoading) {
    return (
      <div className="sandbox-root">
        <div className="sandbox-full-overlay">
          <div className="sandbox-overlay">
            {(phase === 'idle' || phase === 'not_found') && (
              <>
                <p className="sandbox-overlay-title">
                  {phase === 'not_found' ? 'Sandbox no longer exists' : 'No active sandbox'}
                </p>
                <p className="sandbox-overlay-sub">
                  {phase === 'not_found'
                    ? 'The sandbox was deleted or expired. Create a new one to continue.'
                    : 'Spin up a cloud environment with Monaco editor, terminal, and AI agent.'}
                </p>
                <button className="sandbox-btn sandbox-btn-primary" onClick={create}>
                  + Create Sandbox
                </button>
              </>
            )}
            {phase === 'creating' && (
              <>
                <div className="sandbox-spinner" />
                <p className="sandbox-overlay-title">Provisioning{sandboxName ? ` ${sandboxName}` : ''}…</p>
                <p className="sandbox-overlay-sub">Building image · installing packages · starting code-server (2–4 min)</p>
              </>
            )}
            {phase === 'error' && (
              <>
                <p className="sandbox-overlay-title sandbox-error-title">Sandbox error</p>
                <p className="sandbox-overlay-sub sandbox-error-msg">{errorMsg ?? 'Unknown error'}</p>
                <button className="sandbox-btn sandbox-btn-primary" onClick={create}>Retry</button>
              </>
            )}
            {(phase === 'publishing' || phase === 'destroying') && (
              <>
                <div className="sandbox-spinner" />
                <p className="sandbox-overlay-title">
                  {phase === 'publishing' ? 'Publishing changes…' : 'Destroying sandbox…'}
                </p>
              </>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="sandbox-root">

      {/* ── Toolbar ── */}
      <div className="sandbox-toolbar">
        <span className="sandbox-name">{sandboxName ?? '…'}</span>

        <div className="sandbox-toolbar-right">
          {vsCodeUrl && (
            <a
              href={`/sandbox?url=${encodeURIComponent(vsCodeUrl)}`}
              target="_blank"
              rel="noopener noreferrer"
              className="sandbox-btn sandbox-btn-vscode"
            >
              VS Code ↗
            </a>
          )}

          {/* Publish New */}
          <button
            className={`sandbox-btn ${publishMode === 'new' ? 'sandbox-btn-confirm' : 'sandbox-btn-secondary'}`}
            onClick={() => handlePublish('new')}
            disabled={isLoading}
            title="Publish only new (untracked) files"
          >
            {publishMode === 'new' ? 'Confirm new?' : 'Publish New ▸'}
          </button>

          {/* Publish All */}
          <button
            className={`sandbox-btn ${publishMode === 'all' ? 'sandbox-btn-confirm' : 'sandbox-btn-publish'}`}
            onClick={() => handlePublish('all')}
            disabled={isLoading}
            title="Publish all modified + new files"
          >
            {publishMode === 'all' ? 'Confirm all?' : 'Publish All ▸'}
          </button>

          {publishMode && (
            <button className="sandbox-btn sandbox-btn-cancel" onClick={() => setPublishMode(null)}>
              Cancel
            </button>
          )}

          {destroyConfirm ? (
            <>
              <span className="sandbox-destroy-warn">Unsaved changes will be lost.</span>
              <button
                className="sandbox-btn sandbox-btn-destroy"
                onClick={() => { setDestroyConfirm(false); destroy(); }}
                disabled={isLoading}
              >Confirm ✕</button>
              <button
                className="sandbox-btn sandbox-btn-cancel"
                onClick={() => setDestroyConfirm(false)}
              >Keep</button>
            </>
          ) : (
            <button
              className="sandbox-btn sandbox-btn-destroy"
              onClick={() => setDestroyConfirm(true)}
              disabled={isLoading}
            >✕</button>
          )}
        </div>
      </div>

      {/* ── Publish result banner ── */}
      {lastPublish && (
        <div className="sandbox-publish-banner">
          ✓ Published {lastPublish.count} file{lastPublish.count !== 1 ? 's' : ''}
          {lastPublish.published_files.length > 0 && `: ${lastPublish.published_files.join(', ')}`}
        </div>
      )}

      {/* ── Main body ── */}
      <div className="sandbox-body">

        {/* Top row: tree | editor | chat */}
        <div className="sandbox-top-row">

          {/* File tree */}
          <div className="sandbox-tree-pane">
            <div className="sandbox-pane-header">FILES</div>
            <SandboxFileTree
              files={files}
              activePath={activePath}
              scaffoldPath={scaffoldPath}
              onSelect={loadFile}
            />
          </div>

          {/* Monaco editor */}
          <div className="sandbox-editor-pane">
            <div className="sandbox-pane-header">
              <span>{activePath.split('/').pop() ?? 'editor'}</span>
              <button
                className={`sandbox-save-btn ${isDirty ? 'sandbox-save-btn-dirty' : ''}`}
                onClick={saveFile}
                disabled={!isDirty}
              >
                {saveStatus === 'saving' ? 'Saving…' : isDirty ? '● Save' : 'Saved'}
              </button>
            </div>
            {editorLoading ? (
              <div className="sandbox-editor-loading"><div className="sandbox-spinner" /></div>
            ) : (
              <Suspense fallback={<div className="sandbox-editor-loading"><div className="sandbox-spinner" /></div>}>
                <MonacoEditor
                  height="100%"
                  language="python"
                  theme="vs-dark"
                  value={editorContent}
                  onChange={(v) => {
                    const val = v ?? '';
                    setEditorContent(val);
                    setSaveStatus(val === savedContent ? 'saved' : 'unsaved');
                  }}
                  options={{
                    fontSize: 13,
                    fontFamily: "'Courier New', monospace",
                    minimap: { enabled: false },
                    scrollBeyondLastLine: false,
                    wordWrap: 'on',
                    tabSize: 4,
                    automaticLayout: true,
                  }}
                />
              </Suspense>
            )}
          </div>

          {/* Agent chat */}
          <div className="sandbox-chat-pane">
            <div className="sandbox-pane-header">QUANT AGENT</div>
            <div className="sandbox-messages">
              {messages.length === 0 && (
                <p className="sandbox-chat-hint">
                  The agent is focused on <code>{scaffoldPath.split('/').pop()}</code>.
                  Ask it to implement the strategy, explain patterns, or run tests.
                </p>
              )}
              {messages.map((msg, i) => <MessageBubble key={i} msg={msg} />)}
              <div ref={messagesEndRef} />
            </div>
            <div className="sandbox-input-row">
              <textarea
                className="sandbox-input"
                placeholder={isAgentStreaming ? 'Agent responding…' : 'Ask the agent… (Enter to send)'}
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={handleChatKey}
                disabled={isAgentStreaming}
                rows={3}
              />
              <button
                className="sandbox-send-btn"
                onClick={handleChatSend}
                disabled={isAgentStreaming || !chatInput.trim()}
              >▶</button>
            </div>
          </div>
        </div>

        {/* Bottom: Daytona web terminal (port 22222) */}
        {phase === 'ready' && (
          <div className="sandbox-terminal-pane">
            <div className="sandbox-pane-header">
              <span>TERMINAL</span>
              {terminalUrl && (
                <a
                  href={terminalUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="sandbox-btn sandbox-btn-vscode"
                  style={{ fontSize: 10, padding: '2px 8px' }}
                >
                  ↗ pop out
                </a>
              )}
            </div>
            {terminalUrl ? (
              <iframe
                src={terminalUrl}
                className="sandbox-terminal-iframe"
                allow="clipboard-read; clipboard-write"
                title="Sandbox terminal"
              />
            ) : (
              <div className="sandbox-terminal-placeholder">
                Terminal URL unavailable — recreate the sandbox.
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
