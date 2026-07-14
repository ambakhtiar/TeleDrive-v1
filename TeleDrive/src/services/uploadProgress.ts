export interface ActiveUpload {
  queueItemId: number;
  filename: string;
  fileSize: number;
  bytesTransferred: number;
  totalBytes: number;
  status: 'uploading' | 'uploaded' | 'failed';
  error?: string;
  startedAt: number;
}

type Listener = (uploads: ActiveUpload[]) => void;

let activeUploads: Map<number, ActiveUpload> = new Map();
let listeners: Set<Listener> = new Set();

export function getActiveUploads(): ActiveUpload[] {
  return Array.from(activeUploads.values());
}

export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  listener(getActiveUploads());
  return () => { listeners.delete(listener); };
}

export function updateProgress(queueItemId: number, filename: string, fileSize: number, bytesTransferred: number, totalBytes: number) {
  const upload = activeUploads.get(queueItemId);
  if (!upload) {
    activeUploads.set(queueItemId, {
      queueItemId,
      filename,
      fileSize,
      bytesTransferred,
      totalBytes,
      status: 'uploading',
      startedAt: Date.now(),
    });
  } else {
    activeUploads.set(queueItemId, { ...upload, bytesTransferred, totalBytes });
  }
  notify();
}

export function markDone(queueItemId: number, status: 'uploaded' | 'failed', error?: string) {
  const upload = activeUploads.get(queueItemId);
  if (upload) {
    activeUploads.set(queueItemId, { ...upload, status, error, bytesTransferred: upload.totalBytes });
    notify();
  }
  setTimeout(() => {
    activeUploads.delete(queueItemId);
    notify();
  }, 3000);
}

export function clearAll() {
  activeUploads.clear();
  notify();
}

export function resetState() {
  activeUploads.clear();
  listeners.clear();
}

function notify() {
  const snapshot = getActiveUploads();
  for (const listener of listeners) {
    listener(snapshot);
  }
}
