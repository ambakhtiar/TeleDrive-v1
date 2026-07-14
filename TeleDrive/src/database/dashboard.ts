import { getDatabase } from '@/database/client';
import { mapQueueItem, type QueueRow } from '@/database/mapping';
import type { DashboardSummary } from '@/database/types';

interface QueueCounts {
  pendingCount: number;
  uploadingCount: number;
  failedCount: number;
}

interface DailyTotals {
  uploadedTodayCount: number;
  uploadedTodayBytes: number;
}

function todayKey(): string {
  return new Date().toISOString().slice(0, 10);
}

export interface DaySummary {
  day: string;
  fileCount: number;
  totalBytes: number;
}

export async function listDailySummaries(days: number = 14): Promise<DaySummary[]> {
  const database = await getDatabase();
  const rows = await database.getAllAsync<{ day: string; file_count: number; total_bytes: number }>(
    'SELECT day, file_count, total_bytes FROM daily_upload_summaries ORDER BY day DESC LIMIT ?',
    days,
  );
  return rows.map((r) => ({ day: r.day, fileCount: r.file_count, totalBytes: r.total_bytes }));
}

export async function getDashboardSummary(): Promise<DashboardSummary> {
  const database = await getDatabase();
  const counts = await database.getFirstAsync<QueueCounts>(`
    SELECT
      SUM(CASE WHEN status IN ('pending', 'paused') THEN 1 ELSE 0 END) AS pendingCount,
      SUM(CASE WHEN status = 'uploading' THEN 1 ELSE 0 END) AS uploadingCount,
      SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failedCount
    FROM upload_queue
  `);
  const totals = await database.getFirstAsync<DailyTotals>(
    'SELECT file_count AS uploadedTodayCount, total_bytes AS uploadedTodayBytes FROM daily_upload_summaries WHERE day = ?',
    todayKey(),
  );
  const recentRows = await database.getAllAsync<Record<string, unknown>>(
    'SELECT * FROM upload_queue ORDER BY updated_at DESC LIMIT 5',
  );

  return {
    pendingCount: counts?.pendingCount ?? 0,
    uploadingCount: counts?.uploadingCount ?? 0,
    failedCount: counts?.failedCount ?? 0,
    uploadedTodayCount: totals?.uploadedTodayCount ?? 0,
    uploadedTodayBytes: totals?.uploadedTodayBytes ?? 0,
    recentUploads: recentRows.map((row) => mapQueueItem(row as unknown as QueueRow)),
  };
}
