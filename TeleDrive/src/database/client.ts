import * as SQLite from 'expo-sqlite';

const MAX_RETRIES = 3;
const RETRY_DELAY = 500;

let databasePromise: Promise<SQLite.SQLiteDatabase> | undefined;
let schemaInitialized = false;

export async function getDatabase(): Promise<SQLite.SQLiteDatabase> {
  if (!databasePromise) {
    databasePromise = openWithRetry();
  }
  return databasePromise;
}

async function openWithRetry(): Promise<SQLite.SQLiteDatabase> {
  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
    try {
      return await SQLite.openDatabaseAsync('teledrive.db');
    } catch (error) {
      if (attempt === MAX_RETRIES) throw error;
      await new Promise((r) => setTimeout(r, RETRY_DELAY * attempt));
    }
  }
  throw new Error('Failed to open database');
}

export async function initializeDatabase(): Promise<void> {
  const database = await getDatabase();

  // The DDL + migrations are idempotent but expensive; run them only once per
  // process instead of on every screen mount.
  if (!schemaInitialized) {
    await database.execAsync(`
      PRAGMA journal_mode = WAL;
      PRAGMA foreign_keys = ON;

      CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY NOT NULL,
        applied_at INTEGER NOT NULL
      );

      CREATE TABLE IF NOT EXISTS folder_sources (
        id INTEGER PRIMARY KEY NOT NULL,
        tree_uri TEXT NOT NULL UNIQUE,
        display_name TEXT NOT NULL,
        chat_id INTEGER,
        topic_id INTEGER,
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
      );

      CREATE TABLE IF NOT EXISTS routing_rules (
        id INTEGER PRIMARY KEY NOT NULL,
        rule_type TEXT NOT NULL CHECK (rule_type IN ('extension', 'folder')),
        matcher TEXT NOT NULL,
        destination_topic_id INTEGER NOT NULL,
        tags TEXT NOT NULL DEFAULT '',
        enabled INTEGER NOT NULL DEFAULT 1,
        priority INTEGER NOT NULL DEFAULT 0,
        UNIQUE (rule_type, matcher)
      );

      CREATE TABLE IF NOT EXISTS upload_settings (
        setting_key TEXT PRIMARY KEY NOT NULL,
        setting_value TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS upload_queue (
        id INTEGER PRIMARY KEY NOT NULL,
        file_uri TEXT NOT NULL,
        filename TEXT NOT NULL,
        file_size INTEGER NOT NULL,
        checksum TEXT,
        mime_type TEXT,
        modified_time INTEGER NOT NULL,
        source_folder_id INTEGER NOT NULL REFERENCES folder_sources(id) ON DELETE CASCADE,
        destination_topic_id INTEGER,
        status TEXT NOT NULL CHECK (status IN ('pending', 'uploading', 'paused', 'success', 'failed', 'cancelled')),
        retry_count INTEGER NOT NULL DEFAULT 0,
        error_message TEXT,
        telegram_msg_link TEXT,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        UNIQUE (file_uri, file_size, modified_time)
      );

      CREATE TABLE IF NOT EXISTS daily_upload_summaries (
        day TEXT PRIMARY KEY NOT NULL,
        file_count INTEGER NOT NULL DEFAULT 0,
        total_bytes INTEGER NOT NULL DEFAULT 0,
        updated_at INTEGER NOT NULL
      );

      CREATE INDEX IF NOT EXISTS idx_queue_status ON upload_queue(status);
      CREATE INDEX IF NOT EXISTS idx_queue_filename ON upload_queue(filename);
      CREATE INDEX IF NOT EXISTS idx_queue_modified_time ON upload_queue(modified_time DESC);
      CREATE INDEX IF NOT EXISTS idx_queue_source_folder ON upload_queue(source_folder_id);
      CREATE INDEX IF NOT EXISTS idx_queue_status_created ON upload_queue(status, created_at);
      CREATE INDEX IF NOT EXISTS idx_queue_updated ON upload_queue(updated_at DESC);
    `);

    await runMigrations(database);
    schemaInitialized = true;
  }

  // Reclaim any rows left 'uploading' by a previous crashed/killed run so they
  // can be retried. Safe to run on every open (idempotent UPDATE). Done with
  // raw SQL to avoid an import cycle with queue.ts.
  await database.runAsync(
    `UPDATE upload_queue SET status = 'pending', updated_at = ? WHERE status = 'uploading'`,
    Date.now(),
  );
}

async function runMigrations(database: SQLite.SQLiteDatabase): Promise<void> {
  const applied = new Set<number>();
  for (const row of await database.getAllAsync<{ version: number }>('SELECT version FROM schema_version')) {
    applied.add(row.version);
  }

  if (!applied.has(1)) {
    await database.runAsync(
      'INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (1, ?)',
      Date.now(),
    );
    applied.add(1);
  }

  if (!applied.has(2)) {
    try {
      await database.execAsync(
        "ALTER TABLE upload_queue ADD COLUMN temp_file_path TEXT DEFAULT NULL",
      );
    } catch (e: unknown) {
      const msg = String(e);
      if (!msg.includes('duplicate column') && !msg.includes('already exists')) throw e;
    }
    await database.runAsync(
      'INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (2, ?)',
      Date.now(),
    );
    applied.add(2);
  }

  if (!applied.has(3)) {
    await database.execAsync(`
      CREATE TABLE IF NOT EXISTS sync_peers (
        device_id TEXT PRIMARY KEY NOT NULL,
        display_name TEXT NOT NULL,
        last_seen_at INTEGER,
        is_trusted INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL
      );
      CREATE TABLE IF NOT EXISTS sync_outbox (
        id INTEGER PRIMARY KEY NOT NULL,
        event_type TEXT NOT NULL,
        payload TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'failed')),
        created_at INTEGER NOT NULL,
        sent_at INTEGER
      );
      CREATE TABLE IF NOT EXISTS sync_inbox (
        id INTEGER PRIMARY KEY NOT NULL,
        source_device_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        payload TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'applied', 'ignored')),
        created_at INTEGER NOT NULL,
        applied_at INTEGER
      );
    `);
    await database.runAsync(
      'INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (3, ?)',
      Date.now(),
    );
    applied.add(3);
  }

  if (!applied.has(4)) {
    // Migration 4: recreate upload_queue with FK constraint
    await database.execAsync(`
      PRAGMA foreign_keys = OFF;
      CREATE TABLE upload_queue_v4 (
        id INTEGER PRIMARY KEY NOT NULL,
        file_uri TEXT NOT NULL,
        filename TEXT NOT NULL,
        file_size INTEGER NOT NULL,
        checksum TEXT,
        mime_type TEXT,
        modified_time INTEGER NOT NULL,
        source_folder_id INTEGER NOT NULL REFERENCES folder_sources(id) ON DELETE CASCADE,
        destination_topic_id INTEGER,
        status TEXT NOT NULL CHECK (status IN ('pending', 'uploading', 'paused', 'success', 'failed', 'cancelled')),
        retry_count INTEGER NOT NULL DEFAULT 0,
        error_message TEXT,
        telegram_msg_link TEXT,
        temp_file_path TEXT DEFAULT NULL,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        UNIQUE (file_uri, file_size, modified_time)
      );
      INSERT INTO upload_queue_v4 SELECT id, file_uri, filename, file_size, checksum, mime_type, modified_time, source_folder_id, destination_topic_id, status, retry_count, error_message, telegram_msg_link, temp_file_path, created_at, updated_at FROM upload_queue;
      DROP TABLE upload_queue;
      ALTER TABLE upload_queue_v4 RENAME TO upload_queue;
      PRAGMA foreign_keys = ON;
    `);
    await database.runAsync(
      'INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (4, ?)',
      Date.now(),
    );
    applied.add(4);
  }

  if (!applied.has(5)) {
    // Migration 5: add composite and updated_at indexes
    await database.execAsync(`
      CREATE INDEX IF NOT EXISTS idx_queue_status_created ON upload_queue(status, created_at);
      CREATE INDEX IF NOT EXISTS idx_queue_updated ON upload_queue(updated_at DESC);
    `);
    await database.runAsync(
      'INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (5, ?)',
      Date.now(),
    );
    applied.add(5);
  }

  if (!applied.has(6)) {
    // Migration 6: add file_filter column to folder_sources
    try {
      await database.execAsync(
        "ALTER TABLE folder_sources ADD COLUMN file_filter TEXT DEFAULT NULL",
      );
    } catch (e: unknown) {
      const msg = String(e);
      if (!msg.includes('duplicate column') && !msg.includes('already exists')) throw e;
    }
    await database.runAsync(
      'INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (6, ?)',
      Date.now(),
    );
    applied.add(6);
  }
}
