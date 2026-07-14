import { getDatabase } from '@/database/client';

export interface LocalSettings {
  continuousBackup: boolean;
  wifiOnly: boolean;
  chargingOnly: boolean;
  autoDelete: boolean;
  maxConcurrentUploads: number;
  uploadSpeedLimitKBps: number;
}

const defaults: LocalSettings = { continuousBackup: false, wifiOnly: true, chargingOnly: false, autoDelete: false, maxConcurrentUploads: 2, uploadSpeedLimitKBps: 0 };

export async function getLocalSettings(): Promise<LocalSettings> {
  const database = await getDatabase();
  const rows = await database.getAllAsync<{ setting_key: string; setting_value: string }>('SELECT setting_key, setting_value FROM upload_settings');
  const values = new Map(rows.map((row) => [row.setting_key, row.setting_value]));
  return {
    continuousBackup: values.get('continuousBackup') === 'true',
    wifiOnly: values.has('wifiOnly') ? values.get('wifiOnly') === 'true' : defaults.wifiOnly,
    chargingOnly: values.get('chargingOnly') === 'true',
    autoDelete: values.get('autoDelete') === 'true',
    maxConcurrentUploads: Number(values.get('maxConcurrentUploads') ?? defaults.maxConcurrentUploads),
    uploadSpeedLimitKBps: Number(values.get('uploadSpeedLimitKBps') ?? defaults.uploadSpeedLimitKBps),
  };
}

export async function setLocalSetting<Key extends keyof LocalSettings>(key: Key, value: LocalSettings[Key]): Promise<void> {
  const database = await getDatabase();
  await database.runAsync(
    'INSERT INTO upload_settings (setting_key, setting_value) VALUES (?, ?) ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value',
    key,
    String(value),
  );
}
