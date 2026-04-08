'use client';

import { useState, useCallback } from 'react';

interface TreeNode {
  name: string;
  path: string;       // full relative path (for files)
  isFile: boolean;
  children: TreeNode[];
}

function buildTree(paths: string[]): TreeNode[] {
  const root: TreeNode[] = [];

  for (const filePath of paths) {
    const parts = filePath.split('/');
    let nodes = root;

    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      const isFile = i === parts.length - 1;
      let node = nodes.find((n) => n.name === part);

      if (!node) {
        node = { name: part, path: isFile ? filePath : '', isFile, children: [] };
        nodes.push(node);
      }
      nodes = node.children;
    }
  }

  return root;
}

interface TreeNodeViewProps {
  node: TreeNode;
  depth: number;
  activePath: string;
  scaffoldPath: string;
  onSelect: (path: string) => void;
}

function TreeNodeView({ node, depth, activePath, scaffoldPath, onSelect }: TreeNodeViewProps) {
  const [open, setOpen] = useState(
    // Auto-expand directories that contain the scaffold file
    !node.isFile && scaffoldPath.startsWith(node.path + '/') || depth < 3,
  );

  if (node.isFile) {
    const isActive = node.path === activePath;
    const isScaffold = node.path === scaffoldPath;
    return (
      <div
        className={`tree-file ${isActive ? 'tree-file-active' : ''} ${isScaffold ? 'tree-file-scaffold' : ''}`}
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
        onClick={() => onSelect(node.path)}
        title={node.path}
      >
        <span className="tree-icon">📄</span>
        {node.name}
        {isScaffold && <span className="tree-scaffold-badge">new</span>}
      </div>
    );
  }

  return (
    <div>
      <div
        className="tree-dir"
        style={{ paddingLeft: `${depth * 12 + 4}px` }}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="tree-chevron">{open ? '▾' : '▸'}</span>
        {node.name}
      </div>
      {open && node.children.map((child) => (
        <TreeNodeView
          key={child.name}
          node={child}
          depth={depth + 1}
          activePath={activePath}
          scaffoldPath={scaffoldPath}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}

interface SandboxFileTreeProps {
  files: string[];
  activePath: string;
  scaffoldPath: string;
  onSelect: (path: string) => void;
}

export default function SandboxFileTree({
  files,
  activePath,
  scaffoldPath,
  onSelect,
}: SandboxFileTreeProps) {
  const tree = buildTree(files);

  if (files.length === 0) {
    return <div className="tree-empty">No files</div>;
  }

  return (
    <div className="sandbox-tree">
      {tree.map((node) => (
        <TreeNodeView
          key={node.name}
          node={node}
          depth={0}
          activePath={activePath}
          scaffoldPath={scaffoldPath}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}
