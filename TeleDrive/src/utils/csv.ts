import type { UploadQueueItem } from '@/database/types';

export function uploadsToCsv(items: UploadQueueItem[]): string {
  const header = 'Filename,Size (bytes),MIME Type,Status,Source,Uploaded At,Error\n';
  const rows = items.map((item) => {
    const filename = escapeCsv(item.filename);
    const size = String(item.fileSize);
    const mime = escapeCsv(item.mimeType ?? '');
    const status = item.status;
    const source = escapeCsv(String(item.sourceFolderId));
    const uploadedAt = new Date(item.updatedAt).toISOString();
    const error = escapeCsv(item.errorMessage ?? '');
    return `${filename},${size},${mime},${status},${source},${uploadedAt},${error}`;
  });
  return header + rows.join('\n');
}

function escapeCsv(value: string): string {
  if (value.includes(',') || value.includes('"') || value.includes('\n')) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}
