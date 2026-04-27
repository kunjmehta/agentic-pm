'use client';

import { useState, useMemo } from 'react';

export interface CompactTableColumn {
  key: string;
  label: string;
  sortable?: boolean;
  align?: 'left' | 'right' | 'center';
  render?: (value: unknown, row: Record<string, unknown>) => React.ReactNode;
}

interface Props {
  columns: CompactTableColumn[];
  data: Record<string, unknown>[];
  maxHeight?: number;
  showExport?: boolean;
  defaultSort?: { key: string; direction: 'asc' | 'desc' };
  maxRows?: number;
  emptyMessage?: string;
}

export default function CompactTable({
  columns,
  data,
  maxHeight = 400,
  showExport = false,
  defaultSort,
  maxRows,
  emptyMessage = 'No data available',
}: Props) {
  const [sortKey, setSortKey] = useState<string | null>(defaultSort?.key ?? null);
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>(
    defaultSort?.direction ?? 'asc'
  );

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(key);
      setSortDirection('asc');
    }
  };

  const sortedData = useMemo(() => {
    if (!sortKey) return data;

    const sorted = [...data].sort((a, b) => {
      const aVal = a[sortKey];
      const bVal = b[sortKey];

      if (aVal === bVal) return 0;
      if (aVal === null || aVal === undefined) return 1;
      if (bVal === null || bVal === undefined) return -1;

      if (typeof aVal === 'number' && typeof bVal === 'number') {
        return sortDirection === 'asc' ? aVal - bVal : bVal - aVal;
      }

      const aStr = String(aVal);
      const bStr = String(bVal);
      return sortDirection === 'asc'
        ? aStr.localeCompare(bStr)
        : bStr.localeCompare(aStr);
    });

    return sorted;
  }, [data, sortKey, sortDirection]);

  const displayData = maxRows ? sortedData.slice(0, maxRows) : sortedData;

  const exportToCSV = () => {
    const headers = columns.map((col) => col.label).join(',');
    const rows = data.map((row) =>
      columns.map((col) => {
        const value = row[col.key];
        const strValue = String(value ?? '');
        return strValue.includes(',') ? `"${strValue}"` : strValue;
      }).join(',')
    );

    const csv = [headers, ...rows].join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `export-${Date.now()}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  if (data.length === 0) {
    return <div className="compact-table-empty">{emptyMessage}</div>;
  }

  return (
    <div className="compact-table-container">
      {showExport && (
        <div className="compact-table-header">
          <button className="compact-table-export" onClick={exportToCSV}>
            Export CSV
          </button>
        </div>
      )}
      <div className="compact-table-wrapper" style={{ maxHeight: `${maxHeight}px` }}>
        <table className="compact-table">
          <thead>
            <tr>
              {columns.map((col) => (
                <th
                  key={col.key}
                  className={`compact-table-th ${col.align ? `align-${col.align}` : ''} ${
                    col.sortable ? 'sortable' : ''
                  } ${sortKey === col.key ? 'sorted' : ''}`}
                  onClick={() => col.sortable && handleSort(col.key)}
                >
                  <span>{col.label}</span>
                  {col.sortable && sortKey === col.key && (
                    <span className="sort-indicator">
                      {sortDirection === 'asc' ? ' ▲' : ' ▼'}
                    </span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {displayData.map((row, idx) => (
              <tr key={idx} className="compact-table-row">
                {columns.map((col) => {
                  const value = row[col.key];
                  const content = col.render ? col.render(value, row) : String(value ?? '');

                  return (
                    <td
                      key={col.key}
                      className={`compact-table-td ${col.align ? `align-${col.align}` : ''}`}
                    >
                      {content}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {maxRows && data.length > maxRows && (
        <div className="compact-table-footer">
          Showing {maxRows} of {data.length} rows
        </div>
      )}
    </div>
  );
}
