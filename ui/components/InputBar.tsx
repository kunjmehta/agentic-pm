'use client';

import { useRef, useCallback } from 'react';

interface Props {
  onSend: (text: string) => void;
  disabled: boolean;
}

export default function InputBar({ onSend, disabled }: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const autoResize = () => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 200) + 'px';
  };

  const send = useCallback(() => {
    const ta = textareaRef.current;
    const text = ta?.value.trim();
    if (!text || disabled) return;
    onSend(text);
    if (ta) {
      ta.value = '';
      ta.style.height = 'auto';
    }
  }, [disabled, onSend]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  return (
    <div className="input-bar">
      <div className="input-wrap">
        <textarea
          ref={textareaRef}
          placeholder="Message your portfolio manager..."
          disabled={disabled}
          rows={1}
          onInput={autoResize}
          onKeyDown={onKeyDown}
        />
        <button className="send-btn" onClick={send} disabled={disabled} aria-label="Send">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="18" height="18">
            <line x1="12" y1="19" x2="12" y2="5" />
            <polyline points="5 12 12 5 19 12" />
          </svg>
        </button>
      </div>
      <div className="input-hint">Enter to send · Shift+Enter for newline</div>
    </div>
  );
}
