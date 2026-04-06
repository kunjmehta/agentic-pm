'use client';

interface Props { name: string }
export default function ToolBadge({ name }: Props) {
  return <span className="tool-badge">fn: {name}</span>;
}
