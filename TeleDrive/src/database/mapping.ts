import type { UploadQueueItem } from '@/database/types';
import { parseUploadStatus } from '@/database/types';

export interface QueueRow {
  id: number;
  file_uri: string;
  filename: string;
  file_size: number;
  checksum: string | null;
  mime_type: string | null;
  modified_time: number;
  source_folder_id: number;
  destination_topic_id: number | null;
  status: string;
  retry_count: number;
  error_message: string | null;
  telegram_msg_link: string | null;
  temp_file_path: string | null;
  created_at: number;
  updated_at: number;
}

export function toStatus(raw: string): UploadQueueItem['status'] {
  return parseUploadStatus(raw);
}

export function mapQueueItem(row: QueueRow): UploadQueueItem {
  return {
    id: row.id,
    fileUri: row.file_uri,
    filename: row.filename,
    fileSize: row.file_size,
    checksum: row.checksum,
    mimeType: row.mime_type,
    modifiedTime: row.modified_time,
    sourceFolderId: row.source_folder_id,
    destinationTopicId: row.destination_topic_id,
    status: toStatus(row.status),
    retryCount: row.retry_count,
    errorMessage: row.error_message,
    telegramMessageLink: row.telegram_msg_link,
    tempFilePath: row.temp_file_path,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}
