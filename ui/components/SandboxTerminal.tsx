'use client';

import { useEffect, useRef, useState, useCallback, KeyboardEvent } from 'react';

interface TerminalLine {
  type: 'command' | 'output';
  text: string;
}

interface SandboxTerminalProps {
  sandboxId: string;
  apiUrl: string;
}

export default function SandboxTerminal({ sandboxId, apiUrl }: SandboxTerminalProps) {
  const [lines, setLines] = useState<TerminalLine[]>([]);
  const [input, setInput] = useState('');
  const [connected, setConnected] = useState(false);
  const [history, setHistory] = useState<string[]>([]);
  const [histIdx, setHistIdx] = useState(-1);

  const wsRef = useRef<WebSocket | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  // Build WebSocket URL: http://host/v1 → ws://host/v1/sandbox/{id}/terminal
  const wsUrl = apiUrl
    .replace(/^http/, 'ws')
    .replace(/\/v1$/, '') + `/v1/sandbox/${sandboxId}/terminal`;

  const stripAnsi = (s: string) => s.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, '');

  const connect = useCallback(() => {
    if (!mountedRef.current) return;

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) { ws.close(); return; }
      setConnected(true);
    };

    ws.onmessage = (e: MessageEvent<string>) => {
      const clean = stripAnsi(e.data).replace(/\r\n/g, '\n').replace(/\r/g, '\n');
      const text = clean.trimEnd();
      if (!text) return;
      setLines((prev) => [...prev, { type: 'output', text }]);
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      setConnected(false);
      // Auto-reconnect after 4 seconds (sandbox might still be initialising)
      reconnectTimer.current = setTimeout(() => {
        if (mountedRef.current) {
          setLines((prev) => [...prev, { type: 'output', text: '[reconnecting…]' }]);
          connect();
        }
      }, 4000);
    };

    ws.onerror = () => {
      // onclose fires after onerror — let it handle reconnect
    };
  }, [wsUrl]);

  useEffect(() => {
    mountedRef.current = true;
    connect();
    return () => {
      mountedRef.current = false;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [lines]);

  const send = useCallback(() => {
    const cmd = input.trim();
    setInput('');
    setHistIdx(-1);
    setLines((prev) => [...prev, { type: 'command', text: cmd }]);
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(cmd || ' ');
      if (cmd) setHistory((h) => [cmd, ...h.slice(0, 49)]);
    }
  }, [input]);

  const handleKeyDown = useCallback((e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      send();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHistIdx((i) => {
        const next = Math.min(i + 1, history.length - 1);
        if (history[next] !== undefined) setInput(history[next]);
        return next;
      });
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHistIdx((i) => {
        const next = Math.max(i - 1, -1);
        setInput(next === -1 ? '' : (history[next] ?? ''));
        return next;
      });
    } else if (e.key === 'l' && e.ctrlKey) {
      e.preventDefault();
      setLines([]);
    }
  }, [send, history]);

  return (
    <div className="sandbox-terminal" onClick={() => inputRef.current?.focus()}>
      <div className="terminal-header">
        <span>TERMINAL</span>
        <span className={`terminal-status ${connected ? 'terminal-connected' : 'terminal-disconnected'}`}>
          {connected ? '● connected' : '○ connecting…'}
        </span>
      </div>

      <div className="terminal-body">
        {lines.map((line, i) => (
          <div key={i} className={`terminal-line tl-${line.type}`}>
            {line.type === 'command' && <span className="terminal-prompt-sym">$ </span>}
            <span>{line.text}</span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="terminal-input-row">
        <span className="terminal-prompt-sym">$</span>
        <input
          ref={inputRef}
          className="terminal-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={!connected}
          placeholder={connected ? '' : 'connecting…'}
          spellCheck={false}
          autoComplete="off"
          autoCorrect="off"
        />
      </div>
    </div>
  );
}
