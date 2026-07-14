import { getTeleDriveNativeModule, addUploadProgressListener, type BatchUploadItem, type BatchUploadResult, type UploadProgressEvent } from '@/native/TeleDriveModule';
import { claimNextBatch, markUploaded, markFailed, updateMessageLink } from '@/database/queue';
import { getLocalSettings } from '@/database/settings';
import { listFolderSources } from '@/database/folders';
import { listRules, matchRoutingRule } from '@/database/rules';
import { formatBytes } from '@/utils/format';
import { updateProgress, markDone } from '@/services/uploadProgress';
import { setMessageSentListener, setFileProgressListener, sendDocumentToTopic } from '@/services/tdlib';
import type { FolderSource } from '@/database/types';

export interface UploadCallbackEvent {
  queueItemId: number;
  status: 'uploading' | 'uploaded' | 'failed';
  progress: number;
  messageId?: string;
  error?: string;
}

export type UploadListener = (event: UploadCallbackEvent) => void;

let isUploading = false;
let shouldStop = false;

function formatDate(ts: number): string {
  try {
    return new Date(ts).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  } catch {
    return '';
  }
}

function getExtension(filename: string): string {
  const parts = filename.split('.');
  return parts.length > 1 ? parts.pop()!.toLowerCase() : '';
}

export async function runSync(onUpload?: UploadListener): Promise<void> {
  // The JS path owns the foreground (manual) sync and renders live progress.
  // Background / continuous backups are driven exclusively by the native
  // UploadWorker (triggered via the foreground service), which atomically
  // claims 'pending' rows. Triggering both here would double-upload.
  await uploadPendingFiles(onUpload);
}

export async function uploadPendingFiles(onUpload?: UploadListener): Promise<void> {
  if (isUploading) return;
  const settings = await getLocalSettings();
  const maxConcurrent = Math.max(1, Math.min(4, settings.maxConcurrentUploads));
  isUploading = true;
  shouldStop = false;

  const mod = getTeleDriveNativeModule();
  const hasBatchUpload = typeof mod.batchUpload === 'function';

  // Pre-fetch folder and rule data once to avoid DB reads in the upload loop.
  // Use the full folder list (not a fixed 1..20 range) so folders whose id
  // exceeds 20 after deletions are still resolved to their chat/topic.
  const folders = new Map<number, FolderSource>(
    (await listFolderSources()).map((f) => [f.id, f]),
  );
  const rules = await listRules();

  while (!shouldStop) {
    const batch = await claimNextBatch(maxConcurrent);
    if (batch.length === 0) break;

    for (const item of batch) {
      updateProgress(item.id, item.filename, item.fileSize, 0, item.fileSize);
      onUpload?.({ queueItemId: item.id, status: 'uploading', progress: 0 });
    }

    function makeCaption(item: typeof batch[number]): string {
      const folder = folders.get(item.sourceFolderId);
      const folderName = folder?.displayName ?? '';
      const ext = getExtension(item.filename);
      const matchedRule = matchRoutingRule(item.filename, folderName, rules);
      const matched = matchedRule != null ? rules.find((r) => r.destinationTopicId === matchedRule && r.enabled) : null;
      const tags = matched?.tags ?? '';
      const parts: string[] = [item.filename];
      parts.push(`${formatBytes(item.fileSize)} · ${formatDate(item.modifiedTime)}`);
      const hashtags: string[] = [];
      if (ext) hashtags.push(`#${ext}`);
      if (folderName) hashtags.push(`#${folderName.replace(/\s+/g, '_')}`);
      if (tags) {
        tags.split(/[,\s]+/).filter(Boolean).forEach((t) => {
          hashtags.push(`#${t.replace(/^#/, '')}`);
        });
      }
      if (hashtags.length > 0) parts.push(hashtags.join(' '));
      return parts.join('\n');
    }

    if (hasBatchUpload) {
      const items: BatchUploadItem[] = batch.map((item) => {
        const folder = folders.get(item.sourceFolderId);
        return {
          queueItemId: item.id,
          fileUri: item.fileUri,
          chatId: folder?.chatId ?? 0,
          topicId: item.destinationTopicId ?? 0,
          caption: makeCaption(item),
          filename: item.filename,
          fileSize: item.fileSize,
        };
      });

      const unsubProgress = addUploadProgressListener((event: UploadProgressEvent) => {
        updateProgress(event.queueItemId, '', event.totalBytes, event.bytesTransferred, event.totalBytes);
        const pct = event.totalBytes > 0 ? Math.round((event.bytesTransferred / event.totalBytes) * 100) : 0;
        onUpload?.({ queueItemId: event.queueItemId, status: 'uploading', progress: pct });
      });

      try {
        const resultJson = await mod.batchUpload(JSON.stringify(items), maxConcurrent);
        unsubProgress();
        const results: BatchUploadResult[] = JSON.parse(resultJson);

        for (const r of results) {
          if (r.success && r.messageLink) {
            await markUploaded(r.queueItemId, r.messageLink);
            markDone(r.queueItemId, 'uploaded');
            onUpload?.({ queueItemId: r.queueItemId, status: 'uploaded', progress: 100, messageId: r.messageLink });
          } else {
            const errMsg = r.errorMessage ?? 'Unknown error';
            await markFailed(r.queueItemId, errMsg);
            markDone(r.queueItemId, 'failed', errMsg);
            onUpload?.({ queueItemId: r.queueItemId, status: 'failed', progress: 0, error: errMsg });
          }
        }
      } catch (error) {
        unsubProgress();
        const errorMessage = error instanceof Error ? error.message : String(error);
        for (const item of batch) {
          await markFailed(item.id, errorMessage);
          markDone(item.id, 'failed', errorMessage);
          onUpload?.({ queueItemId: item.id, status: 'failed', progress: 0, error: errorMessage });
        }
      }
    } else {
      // Fallback single-upload path via TDLib (no native batch API).
      // Register listeners so the REAL Telegram message id — delivered
      // asynchronously via the tdlib-update events — replaces the provisional
      // link once the send actually succeeds.
      setMessageSentListener((queueItemId, chatId, realMessageId) => {
        if (queueItemId <= 0) return;
        const link = `https://t.me/c/${chatId}/${realMessageId}`;
        void updateMessageLink(queueItemId, link);
        markDone(queueItemId, 'uploaded');
        onUpload?.({ queueItemId, status: 'uploaded', progress: 100, messageId: link });
      });
      setFileProgressListener((queueItemId, bytes, total) => {
        if (queueItemId <= 0) return;
        updateProgress(queueItemId, '', total, bytes, total);
        const pct = total > 0 ? Math.round((bytes / total) * 100) : 0;
        onUpload?.({ queueItemId, status: 'uploading', progress: pct });
      });

      try {
        await Promise.allSettled(
          batch.map(async (item) => {
            try {
              const folder = folders.get(item.sourceFolderId);
              const chatId = folder?.chatId ?? 0;
              const topicId = item.destinationTopicId ?? 0;

              if (!chatId || !topicId) {
                throw new Error('No chat/topic assigned. Link this folder to a topic first.');
              }

              const caption = makeCaption(item);

              // TDLib's InputFileLocal cannot read a content:// SAF URI, so the
              // file must be staged to a local temp path before sending.
              const localPath = await mod.copyUriToTemp(item.fileUri, item.id);
              if (!localPath) {
                throw new Error('Could not stage file for upload');
              }
              const provisionalId = await sendDocumentToTopic(chatId, topicId, localPath, caption, item.id);

              // Provisional link; replaced by the real one via setMessageSentListener.
              const provisionalLink = `https://t.me/c/${chatId}/${provisionalId}`;
              await markUploaded(item.id, provisionalLink);
              markDone(item.id, 'uploaded');
              onUpload?.({ queueItemId: item.id, status: 'uploaded', progress: 100, messageId: provisionalLink });
            } catch (error) {
              const errorMessage = error instanceof Error ? error.message : String(error);
              await markFailed(item.id, errorMessage);
              markDone(item.id, 'failed', errorMessage);
              onUpload?.({ queueItemId: item.id, status: 'failed', progress: 0, error: errorMessage });
            }
          }),
        );
      } finally {
        setMessageSentListener(null);
        setFileProgressListener(null);
      }
    }

    // Stop immediately if paused, rather than waiting out the throttle delay.
    if (shouldStop) break;

    // Apply bandwidth throttle delay
    const limitKBps = settings.uploadSpeedLimitKBps;
    if (limitKBps > 0 && limitKBps < Number.MAX_SAFE_INTEGER) {
      const totalBytes = batch.reduce((sum, b) => sum + b.fileSize, 0);
      if (totalBytes > 0) {
        const delayMs = Math.round((totalBytes / (limitKBps * 1024)) * 1000);
        if (delayMs > 0) {
          await new Promise((resolve) => setTimeout(resolve, Math.min(delayMs, 60_000)));
        }
      }
    } else {
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
  }

  isUploading = false;
}

export async function pauseUploads(): Promise<void> {
  shouldStop = true;
  const mod = getTeleDriveNativeModule();
  await mod.pauseQueue();
}

export async function resumeUploads(): Promise<void> {
  shouldStop = false;
  const mod = getTeleDriveNativeModule();
  await mod.resumeQueue();
}

export function isCurrentlyUploading(): boolean {
  return isUploading;
}
