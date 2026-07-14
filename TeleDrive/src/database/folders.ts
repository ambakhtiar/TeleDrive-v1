import { getDatabase } from '@/database/client';
import type { FolderSource } from '@/database/types';

interface FolderRow {
  id: number;
  tree_uri: string;
  display_name: string;
  chat_id: number | null;
  topic_id: number | null;
  enabled: number;
  file_filter: string | null;
  created_at: number;
  updated_at: number;
}

function mapFolder(row: FolderRow): FolderSource {
  return {
    id: row.id,
    treeUri: row.tree_uri,
    displayName: row.display_name,
    chatId: row.chat_id,
    topicId: row.topic_id,
    enabled: row.enabled === 1,
    fileFilter: row.file_filter,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

export async function listFolderSources(): Promise<FolderSource[]> {
  const database = await getDatabase();
  const rows = await database.getAllAsync<FolderRow>(
    'SELECT * FROM folder_sources ORDER BY enabled DESC, display_name COLLATE NOCASE ASC',
  );
  return rows.map(mapFolder);
}

export async function saveFolderSource(treeUri: string, displayName: string): Promise<void> {
  const database = await getDatabase();
  const now = Date.now();
  await database.runAsync(
    `INSERT INTO folder_sources (tree_uri, display_name, enabled, file_filter, created_at, updated_at)
     VALUES (?, ?, 1, NULL, ?, ?)
     ON CONFLICT(tree_uri) DO UPDATE SET display_name = excluded.display_name, enabled = 1, updated_at = excluded.updated_at`,
    treeUri,
    displayName,
    now,
    now,
  );
}

export async function setFolderSourceEnabled(id: number, enabled: boolean): Promise<void> {
  const database = await getDatabase();
  await database.runAsync(
    'UPDATE folder_sources SET enabled = ?, updated_at = ? WHERE id = ?',
    enabled ? 1 : 0,
    Date.now(),
    id,
  );
}

export async function linkFolderToTopic(id: number, chatId: number, topicId: number): Promise<void> {
  const database = await getDatabase();
  await database.runAsync(
    'UPDATE folder_sources SET chat_id = ?, topic_id = ?, enabled = 1, updated_at = ? WHERE id = ?',
    chatId,
    topicId,
    Date.now(),
    id,
  );
}

export async function updateFolderFileFilter(id: number, fileFilter: string | null): Promise<void> {
  const database = await getDatabase();
  await database.runAsync(
    'UPDATE folder_sources SET file_filter = ?, updated_at = ? WHERE id = ?',
    fileFilter,
    Date.now(),
    id,
  );
}

export async function updateFolderDisplayName(id: number, displayName: string): Promise<void> {
  const database = await getDatabase();
  await database.runAsync(
    'UPDATE folder_sources SET display_name = ?, updated_at = ? WHERE id = ?',
    displayName,
    Date.now(),
    id,
  );
}

export async function getFolderSource(id: number): Promise<FolderSource | null> {
  const database = await getDatabase();
  const row = await database.getFirstAsync<FolderRow>(
    'SELECT * FROM folder_sources WHERE id = ?',
    id,
  );
  return row ? mapFolder(row) : null;
}

export async function deleteFolderSource(id: number): Promise<void> {
  const database = await getDatabase();
  await database.runAsync('DELETE FROM folder_sources WHERE id = ?', id);
}
