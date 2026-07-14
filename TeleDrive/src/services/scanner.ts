import { getTeleDriveNativeModule } from '@/native/TeleDriveModule';
import { listFolderSources } from '@/database/folders';
import { listRules, matchRoutingRule } from '@/database/rules';
import { enqueueFiles } from '@/database/queue';
import type { FolderSource } from '@/database/types';

export interface ScanResult {
  totalFolders: number;
  totalFiles: number;
  enqueued: number;
  skipped: number;
}

/**
 * Scan all enabled folders, enumerate files via SAF, match against routing rules
 * (extension > folder-name > folder fallback topic), and enqueue new files.
 */
export async function scanAllFolders(): Promise<ScanResult> {
  const mod = getTeleDriveNativeModule();
  const folders = await listFolderSources();
  const rules = await listRules();

  const enabledFolders = folders.filter((f) => f.enabled);
  let totalFiles = 0;
  let enqueued = 0;

  for (const folder of enabledFolders) {
    try {
      let files = await mod.scanFolder(folder.treeUri);

      // Apply file type filter if set
      if (folder.fileFilter) {
        const allowed = folder.fileFilter.split(',').map((e) => e.trim().replace(/^\.+/, '').toLowerCase()).filter(Boolean);
        if (allowed.length > 0) {
          files = files.filter((f) => {
            const dotIdx = f.name.lastIndexOf('.');
            if (dotIdx < 0 || dotIdx === f.name.length - 1) return false;
            const ext = f.name.substring(dotIdx + 1).toLowerCase();
            return allowed.some((a) => a === '*' || ext === a);
          });
        }
      }

      totalFiles += files.length;

      const filesWithRoutes = files.map((file) => {
        let topicId = matchRoutingRule(file.name, folder.displayName, rules);
        if (topicId == null) {
          topicId = folder.topicId;
        }
        return { file, topicId, sourceFolderId: folder.id };
      });

      const newCount = await enqueueFiles(
        filesWithRoutes.map((f) => ({
          fileUri: f.file.uri,
          filename: f.file.name,
          fileSize: f.file.size,
          checksum: null,
          mimeType: f.file.mimeType,
          modifiedTime: f.file.lastModified,
          sourceFolderId: f.sourceFolderId,
          destinationTopicId: f.topicId,
        })),
      );

      enqueued += newCount;
    } catch (error) {
      console.error(`Failed to scan folder ${folder.displayName}:`, error);
    }
  }

  return { totalFolders: enabledFolders.length, totalFiles, enqueued, skipped: totalFiles - enqueued };
}

/**
 * Scan a single folder and enqueue new files. Used for per-folder rescan.
 */
export async function scanFolderAndEnqueue(folder: FolderSource): Promise<ScanResult> {
  const mod = getTeleDriveNativeModule();
  const rules = await listRules();

  let files = await mod.scanFolder(folder.treeUri);

  // Apply file type filter if set
  if (folder.fileFilter) {
    const allowed = folder.fileFilter.split(',').map((e) => e.trim().replace(/^\.+/, '').toLowerCase()).filter(Boolean);
    if (allowed.length > 0) {
      files = files.filter((f) => {
        const dotIdx = f.name.lastIndexOf('.');
        if (dotIdx < 0 || dotIdx === f.name.length - 1) return false;
        const ext = f.name.substring(dotIdx + 1).toLowerCase();
        return allowed.some((a) => a === '*' || ext === a);
      });
    }
  }

  const filesWithRoutes = files.map((file) => {
    let topicId = matchRoutingRule(file.name, folder.displayName, rules);
    if (topicId == null) {
      topicId = folder.topicId;
    }
    return { file, topicId, sourceFolderId: folder.id };
  });

  const enqueued = await enqueueFiles(
    filesWithRoutes.map((f) => ({
      fileUri: f.file.uri,
      filename: f.file.name,
      fileSize: f.file.size,
      checksum: null,
      mimeType: f.file.mimeType,
      modifiedTime: f.file.lastModified,
      sourceFolderId: f.sourceFolderId,
      destinationTopicId: f.topicId,
    })),
  );

  return { totalFolders: 1, totalFiles: files.length, enqueued, skipped: files.length - enqueued };
}
