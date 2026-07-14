export type UploadStatus = 'pending' | 'uploading' | 'paused' | 'success' | 'failed' | 'cancelled';

export const VALID_STATUSES: readonly UploadStatus[] = ['pending', 'uploading', 'paused', 'success', 'failed', 'cancelled'];

export function parseUploadStatus(value: string, fallback: UploadStatus = 'pending'): UploadStatus {
  if (VALID_STATUSES.includes(value as UploadStatus)) {
    return value as UploadStatus;
  }
  return fallback;
}

export interface UploadQueueItem {
  id: number;
  fileUri: string;
  filename: string;
  fileSize: number;
  checksum: string | null;
  mimeType: string | null;
  modifiedTime: number;
  sourceFolderId: number;
  destinationTopicId: number | null;
  status: UploadStatus;
  retryCount: number;
  errorMessage: string | null;
  telegramMessageLink: string | null;
  tempFilePath: string | null;
  createdAt: number;
  updatedAt: number;
}

export interface DashboardSummary {
  pendingCount: number;
  uploadingCount: number;
  failedCount: number;
  uploadedTodayCount: number;
  uploadedTodayBytes: number;
  recentUploads: UploadQueueItem[];
}

export interface FolderSource {
  id: number;
  treeUri: string;
  displayName: string;
  chatId: number | null;
  topicId: number | null;
  enabled: boolean;
  fileFilter: string | null;
  createdAt: number;
  updatedAt: number;
}
