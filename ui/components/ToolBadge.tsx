'use client';

interface Props { name: string }
export default function ToolBadge({ name }: Props) {
  return <div className="tool-badge">{name}</div>;
}
