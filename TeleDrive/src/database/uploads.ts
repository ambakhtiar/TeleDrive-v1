import { getDatabase } from '@/database/client';
import { mapQueueItem, type QueueRow } from '@/database/mapping';
import type { UploadQueueItem } from '@/database/types';

export type SortField = 'date' | 'name' | 'size';
export type SortOrder = 'asc' | 'desc';
export type StatusFilter = 'all' | 'success' | 'failed' | 'pending';

export async function listUploadedFiles(
  search: string,
  offset: number,
  sort: SortField = 'date',
  order: SortOrder = 'desc',
  statusFilter: StatusFilter = 'all',
  sourceFolderId?: number | null,
): Promise<UploadQueueItem[]> {
  const database = await getDatabase();
  const conditions: string[] = [];
  const params: (string | number)[] = [];

  if (statusFilter !== 'all') {
    conditions.push('status = ?');
    params.push(statusFilter);
  }

  if (search.trim()) {
    conditions.push('filename LIKE ?');
    params.push(`%${search.trim()}%`);
  }

  if (sourceFolderId != null) {
    conditions.push('source_folder_id = ?');
    params.push(sourceFolderId);
  }

  const where = conditions.length > 0 ? `WHERE ${conditions.join(' AND ')}` : '';

  const SORT_COLUMNS: Record<SortField, string> = {
    name: 'filename',
    size: 'file_size',
    date: 'updated_at',
  };
  const orderDir = order === 'asc' ? 'ASC' : 'DESC';
  const orderBy = `${SORT_COLUMNS[sort]} ${orderDir}`;

  const limit = 20;
  params.push(limit, offset);

  const rows = await database.getAllAsync<QueueRow>(
    `SELECT * FROM upload_queue ${where} ORDER BY ${orderBy} LIMIT ? OFFSET ?`,
    ...params,
  );
  return rows.map(mapQueueItem);
}

export async function listAllUploadedFiles(
  search: string,
  statusFilter: StatusFilter = 'all',
  sourceFolderId?: number | null,
): Promise<UploadQueueItem[]> {
  const database = await getDatabase();
  const conditions: string[] = [];
  const params: (string | number)[] = [];

  if (statusFilter !== 'all') {
    conditions.push('status = ?');
    params.push(statusFilter);
  }

  if (search.trim()) {
    conditions.push('filename LIKE ?');
    params.push(`%${search.trim()}%`);
  }

  if (sourceFolderId != null) {
    conditions.push('source_folder_id = ?');
    params.push(sourceFolderId);
  }

  const where = conditions.length > 0 ? `WHERE ${conditions.join(' AND ')}` : '';
  const rows = await database.getAllAsync<QueueRow>(
    `SELECT * FROM upload_queue ${where} ORDER BY updated_at DESC`,
    ...params,
  );
  return rows.map(mapQueueItem);
}

export async function listPendingItems(): Promise<UploadQueueItem[]> {
  const database = await getDatabase();
  const rows = await database.getAllAsync<QueueRow>(
    "SELECT * FROM upload_queue WHERE status IN ('pending', 'paused') ORDER BY created_at ASC",
  );
  return rows.map(mapQueueItem);
}
