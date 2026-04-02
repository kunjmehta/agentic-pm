'use client';

import { useState } from 'react';
import type { ThinkingBlock } from '@/types';

interface Props {
  block: ThinkingBlock;
}

export default function ThinkingSection({ block }: Props) {
  const [open, setOpen] = useState(false);
  const label = block.agent.charAt(0).toUpperCase() + block.agent.slice(1);
  const suffix =
    block.taskCount !== undefined
      ? ` reasoning (${block.taskCount} tasks)`
      : ' thinking…';

  return (
    <details className="thinking" open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>💭 {label}{suffix}</summary>
      <div className="thinking-content">{block.content}</div>
    </details>
  );
}
