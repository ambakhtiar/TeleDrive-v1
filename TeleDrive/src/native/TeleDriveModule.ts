import { NativeEventEmitter, NativeModules } from 'react-native';

export interface ScannedFile {
  uri: string;
  name: string;
  size: number;
  mimeType: string;
  lastModified: number;
  isDirectory: boolean;
}

export type FileMetadata = ScannedFile;

export interface UploadProgressEvent {
  queueItemId: number;
  bytesTransferred: number;
  totalBytes: number;
  bytesPerSecond: number;
  queuePosition: number;
  state: 'uploading' | 'paused' | 'failed' | 'success';
  errorMessage?: string;
}

export interface SyncStatusEvent {
  status: 'scanning' | 'uploading' | 'idle' | 'error';
  message?: string;
}

export interface TelegramChat {
  id: number;
  title: string;
  type: string;
  isForum: boolean;
}

export interface TelegramTopic {
  id: number;
  name: string;
  messageCount: number;
}

export interface BatchUploadItem {
  queueItemId: number;
  fileUri: string;
  chatId: number;
  topicId: number;
  caption: string;
  filename: string;
  fileSize: number;
}

export interface BatchUploadResult {
  queueItemId: number;
  success: boolean;
  messageLink: string | null;
  errorMessage: string | null;
}

export interface TeleDriveNativeModule {
  pickFolder(): Promise<{ treeUri: string; displayName: string } | null>;
  scanFolder(treeUri: string): Promise<ScannedFile[]>;
  syncNow(): Promise<void>;
  pauseQueue(): Promise<void>;
  resumeQueue(): Promise<void>;

  deleteFile(uri: string): Promise<boolean>;
  isWifiConnected(): Promise<boolean>;
  isDeviceCharging(): Promise<boolean>;
  scheduleContinuousBackup(): Promise<void>;
  cancelContinuousBackup(): Promise<void>;
  syncSettings(settings: { wifiOnly: boolean; chargingOnly: boolean; autoDelete: boolean; maxConcurrentUploads: number }): Promise<void>;

  loadChats(): Promise<boolean>;
  getChats(): Promise<TelegramChat[]>;
  getForumTopics(chatId: number): Promise<TelegramTopic[]>;
  createForumTopic(chatId: number, name: string): Promise<TelegramTopic>;
  startForegroundService(): Promise<void>;
  stopForegroundService(): Promise<void>;

  storeApiCredentials(apiId: number, apiHash: string): Promise<void>;
  batchUpload(uploadsJson: string, maxConcurrent: number): Promise<string>;
  copyUriToTemp(uri: string, queueItemId: number): Promise<string | null>;
}

const nativeModule = NativeModules.TeleDrive as TeleDriveNativeModule | undefined;

export const isTeleDriveNativeModuleAvailable = nativeModule !== undefined;

export function getTeleDriveNativeModule(): TeleDriveNativeModule {
  if (!nativeModule) {
    throw new Error('TeleDrive native services are unavailable. Install an Android development build.');
  }
  return nativeModule;
}

export function addUploadProgressListener(listener: (event: UploadProgressEvent) => void): () => void {
  if (!nativeModule) {
    return () => undefined;
  }
  const subscription = new NativeEventEmitter(NativeModules.TeleDrive).addListener('uploadProgress', listener);
  return () => subscription.remove();
}
