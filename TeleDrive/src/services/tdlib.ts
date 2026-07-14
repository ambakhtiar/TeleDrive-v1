import { NativeEventEmitter, NativeModules } from 'react-native';

let initialized = false;
let emitterSubscription: { remove: () => void } | null = null;
let authState: AuthState = 'closed';
let authListeners: Set<(state: AuthState) => void> = new Set();

interface PendingUpload {
  queueItemId: number;
  filePath: string;
  chatId: number;
  topicId: number;
}

const pendingUploads: PendingUpload[] = [];
// "chatId:topicId" → queue of queueItemIds awaiting their message id (FIFO).
const pendingSendByTopic = new Map<string, number[]>();

export type FileProgressListener = (queueItemId: number, bytesTransferred: number, totalBytes: number) => void;
export type MessageSentListener = (queueItemId: number, chatId: number, realMessageId: number) => void;

let fileProgressListener: FileProgressListener | null = null;
let messageSentListener: MessageSentListener | null = null;

export function setFileProgressListener(listener: FileProgressListener | null): void {
  fileProgressListener = listener;
}

export function setMessageSentListener(listener: MessageSentListener | null): void {
  messageSentListener = listener;
}

export type AuthState = 'unknown' | 'ready' | 'waitPhoneNumber' | 'waitCode' | 'waitPassword' | 'loading' | 'closed';
export type AuthStateType = AuthState;

function getTdLibModule(): { startTdLib: (params: Record<string, unknown>) => Promise<string>; login: (details: Record<string, string>) => Promise<string>; verifyPhoneNumber: (code: string) => Promise<string>; verifyPassword: (password: string) => Promise<string>; getAuthorizationState: () => Promise<string>; logout: () => Promise<string>; destroy: () => Promise<string>; loadChats: (limit: number) => Promise<string>; getChats: (limit: number) => Promise<string>; searchChats: (query: string, limit: number) => Promise<string>; td_json_client_send: (request: Record<string, unknown>) => Promise<string>; addMessageReaction: (chatId: number, messageId: number, emoji: string) => Promise<string>; } | null {
  try {
    return NativeModules.TdLibModule ?? null;
  } catch {
    return null;
  }
}

function emitAuthState(state: AuthState) {
  authState = state;
  for (const listener of authListeners) {
    listener(state);
  }
}

export function onAuthStateChanged(listener: (state: AuthState) => void): () => void {
  authListeners.add(listener);
  listener(authState);
  return () => {
    authListeners.delete(listener);
  };
}

export const onAuthStateChange = onAuthStateChanged;

export async function fetchAuthState(): Promise<AuthState> {
  return authState;
}

export function initAuthListener(): () => void {
  // Already initialized via initTdLib — just subscribe to changes
  return onAuthStateChanged(() => {});
}

export function getAuthState(): AuthState {
  return authState;
}

export async function initTdLib(apiId: number, apiHash: string): Promise<void> {
  const tdlib = getTdLibModule();
  if (!tdlib) throw new Error('TDLib native module not available');
  if (initialized) return;

  emitterSubscription?.remove();
  const emitter = new NativeEventEmitter(NativeModules.TdLibModule);
  emitterSubscription = emitter.addListener('tdlib-update', (event: { type: string; raw: string }) => {
    if (event.type === 'updateAuthorizationState') {
      try {
        const data = JSON.parse(event.raw);
        const state = data.authorization_state?.['@type'] ?? '';
        if (state.includes('Ready')) emitAuthState('ready');
        else if (state.includes('WaitPhoneNumber')) emitAuthState('waitPhoneNumber');
        else if (state.includes('WaitCode')) emitAuthState('waitCode');
        else if (state.includes('WaitPassword')) emitAuthState('waitPassword');
        else if (state.includes('Closed')) emitAuthState('closed');
      } catch { /* ignore parse errors */ }
    }

    if (event.type === 'updateFile') {
      try {
        const data = JSON.parse(event.raw);
        const file = data.file;
        if (file?.local?.path && file.is_uploading) {
          const pending = pendingUploads.find((p) => p.filePath === file.local.path);
          if (pending) {
            fileProgressListener?.(pending.queueItemId, file.uploaded_size ?? 0, file.expected_size ?? 0);
          }
        }
      } catch { /* ignore */ }
    }

    if (event.type === 'updateMessageSendSucceeded') {
      try {
        const data = JSON.parse(event.raw);
        const msg = data.message;
         if (msg?.id) {
           const key = `${msg.chat_id}:${msg.message_thread_id ?? 0}`;
           const queue = pendingSendByTopic.get(key);
           const queueItemId = queue?.shift();
           if (queue && queue.length === 0) pendingSendByTopic.delete(key);
           if (queueItemId != null) {
             messageSentListener?.(queueItemId, msg.chat_id, msg.id);
           }
         }
      } catch { /* ignore */ }
    }
  });

  await tdlib.startTdLib({
    api_id: apiId,
    api_hash: apiHash,
    device_model: 'TeleDrive Android',
    system_version: '1.0',
    application_version: '1.0',
    system_language_code: 'en',
  });

  initialized = true;

  // Store credentials for Worker background uploads
  try {
    const teleDrive = NativeModules.TeleDrive;
    if (teleDrive?.storeApiCredentials) {
      await teleDrive.storeApiCredentials(apiId, apiHash);
    }
  } catch { /* ok if module not available */ }

  try {
    const stateJson = await tdlib.getAuthorizationState();
    const stateData = JSON.parse(stateJson);
    const type = stateData?.['@type'] ?? '';
    if (type.includes('Ready')) emitAuthState('ready');
    else if (type.includes('WaitPhoneNumber')) emitAuthState('waitPhoneNumber');
    else emitAuthState('waitPhoneNumber');
  } catch {
    emitAuthState('waitPhoneNumber');
  }
}

export async function loginWithPhone(phoneNumber: string): Promise<void> {
  const tdlib = getTdLibModule();
  if (!tdlib) throw new Error('TDLib native module not available');
  emitAuthState('loading');
  const cleaned = phoneNumber.replace(/\s/g, '');
  const normalized = cleaned.startsWith('+') ? cleaned : '+' + cleaned;
  await tdlib.login({ countrycode: '', phoneNumber: normalized });
}

export const requestPhoneCode = loginWithPhone;

export async function verifyCode(code: string): Promise<void> {
  const tdlib = getTdLibModule();
  if (!tdlib) throw new Error('TDLib native module not available');
  await tdlib.verifyPhoneNumber(code);
}

export async function verifyPassword(password: string): Promise<void> {
  const tdlib = getTdLibModule();
  if (!tdlib) throw new Error('TDLib native module not available');
  await tdlib.verifyPassword(password);
}

export async function logoutTdLib(): Promise<void> {
  const tdlib = getTdLibModule();
  if (!tdlib) throw new Error('TDLib native module not available');
  await tdlib.logout();
  emitAuthState('closed');
}

export async function loadForumGroups(): Promise<{ chatId: number; title: string; type: string }[]> {
  const tdlib = getTdLibModule();
  if (!tdlib) throw new Error('TDLib native module not available');

  const groups: { chatId: number; title: string; type: string }[] = [];
  try {
    await tdlib.loadChats(100);
    const chatsJson = await tdlib.getChats(100);
    const chats = JSON.parse(chatsJson);
    if (Array.isArray(chats)) {
      for (const chat of chats) {
        if (chat.type?.['@type'] === 'chatTypeSupergroup' && chat.type?.is_forum) {
          groups.push({ chatId: chat.id, title: chat.title, type: 'forum' });
        }
      }
    }
  } catch { /* ignore */ }
  return groups;
}

export async function getForumTopics(chatId: number): Promise<{ topicId: number; name: string; isGeneral: boolean }[]> {
  const tdlib = getTdLibModule();
  if (!tdlib) throw new Error('TDLib native module not available');

  try {
    const result = await tdlib.td_json_client_send({
      '@type': 'getForumTopics',
      chat_id: chatId,
      query: '',
      limit: 50,
      offset_message_id: 0,
      offset_date: 0,
    });
    const data = JSON.parse(result);
    const topics: { topicId: number; name: string; isGeneral: boolean }[] = [];
    if (data.topics && Array.isArray(data.topics)) {
      for (const t of data.topics) {
        topics.push({
          topicId: t.id,
          name: t.name ?? 'General',
          isGeneral: t.id === 1,
        });
      }
    }
    return topics;
  } catch {
    return [];
  }
}

export async function createForumTopic(chatId: number, name: string): Promise<{ topicId: number; name: string }> {
  const tdlib = getTdLibModule();
  if (!tdlib) throw new Error('TDLib native module not available');

  const result = await tdlib.td_json_client_send({
    '@type': 'createForumTopic',
    chat_id: chatId,
    name,
    icon_color: Math.floor(Math.random() * 8) + 1,
  });
  const data = JSON.parse(result);
  return {
    topicId: data.id,
    name: data.name ?? name,
  };
}

export async function sendDocumentToTopic(
  chatId: number,
  topicId: number,
  filePath: string,
  caption: string,
  queueItemId: number,
): Promise<string> {
  const tdlib = getTdLibModule();
  if (!tdlib) throw new Error('TDLib native module not available');

  const messageId = Date.now();

  pendingUploads.push({ queueItemId, filePath, chatId, topicId });
  const key = `${chatId}:${topicId}`;
  const queue = pendingSendByTopic.get(key) ?? [];
  queue.push(queueItemId);
  pendingSendByTopic.set(key, queue);

  await tdlib.td_json_client_send({
    '@type': 'sendMessage',
    chat_id: chatId,
    message_thread_id: topicId,
    reply_to: null,
    options: null,
    input_message_content: {
      '@type': 'inputMessageDocument',
      document: {
        '@type': 'inputFileLocal',
        path: filePath,
      },
      caption: {
        '@type': 'formattedText',
        text: caption,
        entities: [],
      },
    },
  });

  setTimeout(() => {
    const idx = pendingUploads.findIndex((p) => p.queueItemId === queueItemId);
    if (idx >= 0) pendingUploads.splice(idx, 1);
    const existingKey = `${chatId}:${topicId}`;
    const list = pendingSendByTopic.get(existingKey);
    if (list) {
      const li = list.indexOf(queueItemId);
      if (li >= 0) list.splice(li, 1);
      if (list.length === 0) pendingSendByTopic.delete(existingKey);
    }
  }, 60_000);

  return String(messageId);
}
