import { getDatabase } from '@/database/client';
import { mapQueueItem, type QueueRow } from '@/database/mapping';
import type { UploadQueueItem } from '@/database/types';

export async function enqueueFiles(
  files: {
    fileUri: string;
    filename: string;
    fileSize: number;
    checksum: string | null;
    mimeType: string | null;
    modifiedTime: number;
    sourceFolderId: number;
    destinationTopicId: number | null;
  }[],
): Promise<number> {
  const database = await getDatabase();
  let count = 0;

  await database.execAsync('BEGIN TRANSACTION');
  try {
    for (const file of files) {
      const now = Date.now();
      const result = await database.runAsync(
        `INSERT OR IGNORE INTO upload_queue
         (file_uri, filename, file_size, checksum, mime_type, modified_time,
          source_folder_id, destination_topic_id, status, retry_count, error_message, created_at, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, NULL, ?, ?)`,
        file.fileUri, file.filename, file.fileSize, file.checksum, file.mimeType,
        file.modifiedTime, file.sourceFolderId, file.destinationTopicId, now, now,
      );
      if (result.changes > 0) count++;
    }
    await database.execAsync('COMMIT');
  } catch (e) {
    await database.execAsync('ROLLBACK');
    throw e;
  }

  return count;
}

/**
 * Atomically claim the next batch of pending files for upload.
 * Uses a single UPDATE to avoid TOCTOU race between SELECT and UPDATE.
 */
export async function claimNextBatch(limit: number): Promise<UploadQueueItem[]> {
  const database = await getDatabase();
  const now = Date.now();
  await database.execAsync('BEGIN TRANSACTION');
  try {
    // Get the IDs of pending items (oldest first)
    const pendingIds = await database.getAllAsync<{ id: number }>(
      `SELECT id FROM upload_queue
       WHERE status = 'pending'
       ORDER BY created_at ASC
       LIMIT ?`,
      limit,
    );
    if (pendingIds.length === 0) {
      await database.execAsync('COMMIT');
      return [];
    }
    // Atomically mark them as uploading
    const ids = pendingIds.map((r) => r.id);
    const placeholders = ids.map(() => '?').join(',');
    await database.runAsync(
      `UPDATE upload_queue SET status = 'uploading', updated_at = ? WHERE id IN (${placeholders})`,
      now,
      ...ids,
    );
    // Read back the claimed items
    const rows = await database.getAllAsync<QueueRow>(
      `SELECT * FROM upload_queue WHERE id IN (${placeholders}) ORDER BY created_at ASC`,
      ...ids,
    );
    await database.execAsync('COMMIT');
    return rows.map(mapQueueItem);
  } catch (e) {
    await database.execAsync('ROLLBACK');
    throw e;
  }
}

/**
 * Mark a queue item as uploaded successfully and update daily summary.
 */
export async function markUploaded(id: number, telegramMessageLink: string): Promise<void> {
  const database = await getDatabase();
  const now = Date.now();

  await database.execAsync('BEGIN TRANSACTION');
  try {
    const item = await database.getFirstAsync<{ file_size: number }>(
      'SELECT file_size FROM upload_queue WHERE id = ?', id,
    );
    await database.runAsync(
      `UPDATE upload_queue SET status = 'success', telegram_msg_link = ?, updated_at = ? WHERE id = ?`,
      telegramMessageLink,
      now,
      id,
    );
    if (item) {
      const day = new Date(now).toISOString().slice(0, 10);
      await database.runAsync(
        `INSERT INTO daily_upload_summaries (day, file_count, total_bytes, updated_at)
         VALUES (?, 1, ?, ?)
         ON CONFLICT(day) DO UPDATE SET
           file_count = file_count + 1,
           total_bytes = total_bytes + excluded.total_bytes,
           updated_at = excluded.updated_at`,
        day, item.file_size, now,
      );
    }
    await database.execAsync('COMMIT');
  } catch (e) {
    await database.execAsync('ROLLBACK');
    throw e;
  }
}

/**
 * Mark a queue item as failed.
 */
export async function markFailed(id: number, errorMessage: string): Promise<void> {
  const database = await getDatabase();
  const now = Date.now();
  await database.runAsync(
    `UPDATE upload_queue SET status = 'failed', error_message = ?, retry_count = retry_count + 1, updated_at = ? WHERE id = ?`,
    errorMessage,
    now,
    id,
  );
}

/**
 * Retry failed items (reset to pending if retry count < 3).
 */
export async function retryFailed(id: number): Promise<void> {
  const database = await getDatabase();
  const now = Date.now();
  await database.runAsync(
    `UPDATE upload_queue SET status = 'pending', error_message = NULL, updated_at = ?
     WHERE id = ? AND retry_count < 3`,
    now,
    id,
  );
}

/**
 * Retry all failed items (reset to pending if retry count < 3).
 * Returns the number of items retried.
 */
export async function retryAllFailed(): Promise<number> {
  const database = await getDatabase();
  const now = Date.now();
  const result = await database.runAsync(
    `UPDATE upload_queue SET status = 'pending', error_message = NULL, updated_at = ?
     WHERE status = 'failed' AND retry_count < 3`,
    now,
  );
  return result.changes;
}

/**
 * Cancel a queue item.
 */
export async function cancelItem(id: number): Promise<void> {
  const database = await getDatabase();
  await database.runAsync(
    `UPDATE upload_queue SET status = 'cancelled', updated_at = ? WHERE id = ?`,
    Date.now(),
    id,
  );
}

export async function listQueueItems(): Promise<UploadQueueItem[]> {
  const database = await getDatabase();
  const rows = await database.getAllAsync<QueueRow>(
    'SELECT * FROM upload_queue ORDER BY updated_at DESC',
  );
  return rows.map(mapQueueItem);
}

/**
 * Update the Telegram message link for a queue item (used when real message ID arrives).
 */
export async function updateMessageLink(id: number, link: string): Promise<void> {
  const database = await getDatabase();
  await database.runAsync(
    'UPDATE upload_queue SET telegram_msg_link = ?, updated_at = ? WHERE id = ?',
    link,
    Date.now(),
    id,
  );
}
