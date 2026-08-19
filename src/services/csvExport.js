export function exportRowsAsCsv(fileName, columns, rows) {
  if (!Array.isArray(columns) || !columns.length) {
    throw new Error('columns are required for CSV export');
  }

  const escapeCell = (value) => {
    if (value === null || value === undefined) return '';
    const normalized = String(value).replace(/\r?\n|\r/g, ' ');
    if (/[",]/.test(normalized)) {
      return `"${normalized.replace(/"/g, '""')}"`;
    }
    return normalized;
  };

  const header = columns.map((col) => escapeCell(col.header)).join(',');
  const body = (rows || [])
    .map((row) => columns.map((col) => escapeCell(row[col.key])).join(','))
    .join('\n');

  const csvText = `${header}\n${body}`;
  const blob = new Blob([csvText], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);

  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = fileName;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();

  URL.revokeObjectURL(url);
}
