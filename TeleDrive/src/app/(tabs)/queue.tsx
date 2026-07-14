import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Alert, FlatList, Linking, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { initializeDatabase } from '@/database/client';
import type { UploadQueueItem } from '@/database/types';
import { listQueueItems, retryAllFailed, cancelItem, retryFailed } from '@/database/queue';
import { runSync, pauseUploads, resumeUploads } from '@/services/upload';
import { formatBytes } from '@/utils/format';

export default function QueueScreen() {
  const [items, setItems] = useState<UploadQueueItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [progress, setProgress] = useState<Record<number, number>>({});
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());

  const refresh = useCallback(async () => {
    setLoading(true);
    await initializeDatabase();
    setItems(await listQueueItems());
    setLoading(false);
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const handleSync = async () => {
    setWorking(true);
    try {
      await runSync((event) => {
        if (event.status === 'uploading') {
          setProgress((prev) => ({ ...prev, [event.queueItemId]: event.progress }));
        } else {
          setProgress((prev) => {
            const next = { ...prev };
            delete next[event.queueItemId];
            return next;
          });
        }
      });
      await refresh();
    } catch (error) {
      Alert.alert('Sync failed', error instanceof Error ? error.message : 'Try again later.');
    } finally {
      setProgress({});
      setWorking(false);
    }
  };

  const handlePause = async () => {
    setWorking(true);
    try {
      await pauseUploads();
      await refresh();
    } finally {
      setWorking(false);
    }
  };

  const handleResume = async () => {
    setWorking(true);
    try {
      await resumeUploads();
      await handleSync();
    } finally {
      setWorking(false);
    }
  };

  const handleRetryAll = async () => {
    const count = await retryAllFailed();
    Alert.alert('Retried', `${count} items moved to pending.`);
    await refresh();
  };

  const handleRetryItem = useCallback(async (item: UploadQueueItem) => {
    await retryFailed(item.id);
    await refresh();
  }, [refresh]);

  const handleCancel = useCallback((item: UploadQueueItem) => {
    Alert.alert('Cancel upload?', `Remove "${item.filename}" from the queue?`, [
      { text: 'No', style: 'cancel' },
      { text: 'Cancel', style: 'destructive', onPress: () => void cancelItem(item.id).then(refresh) },
    ]);
  }, [refresh]);

  const toggleSelect = useCallback((id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleSelectAll = useCallback(() => {
    setSelectedIds((prev) => {
      if (prev.size === items.length) return new Set();
      return new Set(items.map((i) => i.id));
    });
  }, [items]);

  const handleBatchRetry = useCallback(async () => {
    const failed = items.filter((i) => selectedIds.has(i.id) && i.status === 'failed');
    if (failed.length === 0) {
      Alert.alert('No failed items selected');
      return;
    }
    for (const item of failed) {
      await retryFailed(item.id);
    }
    setSelectedIds(new Set());
    Alert.alert('Retried', `${failed.length} items moved to pending.`);
    await refresh();
  }, [items, selectedIds, refresh]);

  const handleBatchCancel = useCallback(async () => {
    const cancellable = items.filter(
      (i) => selectedIds.has(i.id) && i.status !== 'success' && i.status !== 'cancelled',
    );
    if (cancellable.length === 0) {
      Alert.alert('No cancellable items selected');
      return;
    }
    Alert.alert('Cancel selected?', `Remove ${cancellable.length} items from the queue?`, [
      { text: 'No', style: 'cancel' },
      {
        text: 'Cancel all', style: 'destructive',
        onPress: async () => {
          for (const item of cancellable) {
            await cancelItem(item.id);
          }
          setSelectedIds(new Set());
          await refresh();
        },
      },
    ]);
  }, [items, selectedIds, refresh]);

  const { pendingCount, uploadingCount, failedCount, queueActive } = useMemo(() => ({
    pendingCount: items.filter((i) => i.status === 'pending').length,
    uploadingCount: items.filter((i) => i.status === 'uploading').length,
    failedCount: items.filter((i) => i.status === 'failed').length,
    queueActive: items.some((i) => i.status === 'uploading'),
  }), [items]);

  const renderItem = useCallback(({ item }: { item: UploadQueueItem }) => (
    <QueueItem
      item={item}
      progress={progress[item.id] ?? 0}
      selectMode={selectMode}
      isSelected={selectedIds.has(item.id)}
      onRetry={handleRetryItem}
      onCancel={handleCancel}
      onToggle={toggleSelect}
    />
  ), [progress, selectMode, selectedIds, handleRetryItem, handleCancel, toggleSelect]);

  return (
    <SafeAreaView style={styles.safe}>
      <FlatList
        data={items}
        keyExtractor={(item) => String(item.id)}
        renderItem={renderItem}
        contentContainerStyle={styles.content}
        ListHeaderComponent={
          <>
            <Text style={styles.title}>Upload queue</Text>
            <Text style={styles.copy}>Files waiting to be uploaded to your Telegram topics.</Text>

            <View style={styles.statsRow}>
              <Stat value={String(pendingCount)} label="pending" />
              <Stat value={String(uploadingCount)} label="active" />
              <Stat value={String(failedCount)} label="failed" />
              <Stat value={queueActive ? '1' : '0'} label="slots" />
            </View>

            <View style={styles.actions}>
              <Button label={working ? 'Working...' : 'Sync now'} disabled={working} onPress={() => void handleSync()} />
              <Button label="Pause" disabled={working} onPress={() => void handlePause()} />
              <Button label="Resume" disabled={working} onPress={() => void handleResume()} />
            </View>

            {failedCount > 0 && !selectMode && (
              <Pressable onPress={() => void handleRetryAll()} style={styles.retryAllBtn}>
                <Text style={styles.retryAllText}>Retry all failed ({failedCount})</Text>
              </Pressable>
            )}

            <Pressable onPress={() => { setSelectMode(!selectMode); setSelectedIds(new Set()); }} style={styles.selectToggle}>
              <Text style={styles.selectToggleText}>{selectMode ? 'Done' : 'Select'}</Text>
            </Pressable>

            {selectMode && selectedIds.size > 0 && (
              <View style={styles.batchActions}>
                <Pressable onPress={() => void handleBatchRetry()} style={styles.batchBtn}>
                  <Text style={styles.batchBtnText}>Retry ({[...selectedIds].filter((id) => items.find((i) => i.id === id)?.status === 'failed').length})</Text>
                </Pressable>
                <Pressable onPress={() => void handleBatchCancel()} style={styles.batchBtnDanger}>
                  <Text style={styles.batchBtnText}>Cancel ({selectedIds.size})</Text>
                </Pressable>
                <Pressable onPress={toggleSelectAll} style={styles.batchBtn}>
                  <Text style={styles.batchBtnText}>
                    {selectedIds.size === items.length ? 'Deselect all' : 'Select all'}
                  </Text>
                </Pressable>
              </View>
            )}
          </>
        }
        ListEmptyComponent={
          loading ? (
            <ActivityIndicator color="#49a7ff" />
          ) : (
            <View style={styles.card}>
              <Text style={styles.name}>Queue empty</Text>
              <Text style={styles.copy}>Tap &quot;Sync now&quot; to scan folders and enqueue new files.</Text>
            </View>
          )
        }
      />
    </SafeAreaView>
  );
}

const QueueItem = React.memo(function QueueItem({
  item, progress, selectMode, isSelected, onRetry, onCancel, onToggle,
}: {
  item: UploadQueueItem;
  progress: number;
  selectMode: boolean;
  isSelected: boolean;
  onRetry: (item: UploadQueueItem) => void;
  onCancel: (item: UploadQueueItem) => void;
  onToggle: (id: number) => void;
}) {
  const pct = progress;
  return (
    <Pressable onPress={selectMode ? () => onToggle(item.id) : undefined} style={[styles.card, item.status === 'failed' && styles.cardFailed, isSelected && styles.cardSelected]}>
      <View style={styles.itemRow}>
        {selectMode && (
          <Pressable onPress={() => onToggle(item.id)} style={styles.checkbox}>
            <Text style={styles.checkboxText}>{isSelected ? '✓' : ''}</Text>
          </Pressable>
        )}
        <View style={styles.itemInfo}>
          <Text numberOfLines={1} style={styles.name}>{item.filename}</Text>
          <Text style={styles.meta}>{formatBytes(item.fileSize)} · {item.status} · retry {item.retryCount}</Text>
          {item.errorMessage && <Text style={styles.error}>{item.errorMessage}</Text>}
          {item.status === 'uploading' && pct > 0 && (
            <View style={styles.progressTrack}>
              <View style={[styles.progressFill, { width: `${Math.min(100, pct)}%` }]} />
              <Text style={styles.progressLabel}>{pct}%</Text>
            </View>
          )}
          {item.telegramMessageLink && (
            <Pressable onPress={() => {
              Linking.openURL(item.telegramMessageLink!).catch(() => {
                Alert.alert('Could not open link', 'Telegram may not be installed.');
              });
            }}>
              <Text style={styles.link}>View on Telegram</Text>
            </Pressable>
          )}
        </View>
        {!selectMode && item.status !== 'success' && item.status !== 'cancelled' && (
          <View style={styles.itemActions}>
            {item.status === 'failed' && (
              <Pressable onPress={() => onRetry(item)}>
                <Text style={styles.retryBtn}>Retry</Text>
              </Pressable>
            )}
            <Pressable onPress={() => onCancel(item)}>
              <Text style={styles.cancelBtn}>X</Text>
            </Pressable>
          </View>
        )}
      </View>
    </Pressable>
  );
});

const Stat = React.memo(function Stat({ value, label }: { value: string; label: string }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.statValue}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
});

const Button = React.memo(function Button({ label, disabled, onPress }: { label: string; disabled: boolean; onPress: () => void }) {
  return (
    <Pressable disabled={disabled} onPress={onPress} style={({ pressed }) => [styles.button, (pressed || disabled) && styles.muted]}>
      <Text style={styles.buttonText}>{label}</Text>
    </Pressable>
  );
});

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#09121f' },
  content: { padding: 20, gap: 14, paddingBottom: 40 },
  title: { color: '#fff', fontSize: 28, fontWeight: '800' },
  copy: { color: '#aabdd0', lineHeight: 20 },
  statsRow: { flexDirection: 'row', justifyContent: 'space-between' },
  stat: { alignItems: 'center' },
  statValue: { color: '#fff', fontSize: 18, fontWeight: '800' },
  statLabel: { color: '#91a6bf', fontSize: 11, marginTop: 2 },
  actions: { flexDirection: 'row', gap: 8 },
  button: { backgroundColor: '#248de9', padding: 12, borderRadius: 10, flex: 1, alignItems: 'center' },
  muted: { opacity: 0.55 },
  buttonText: { color: '#fff', fontWeight: '800', fontSize: 13 },
  retryAllBtn: { backgroundColor: '#5a2633', padding: 12, borderRadius: 10, alignItems: 'center' },
  retryAllText: { color: '#ffd8df', fontWeight: '800' },
  card: { backgroundColor: '#101e30', padding: 14, borderRadius: 14, gap: 5 },
  cardFailed: { borderLeftWidth: 3, borderLeftColor: '#ff5c7c' },
  cardSelected: { borderColor: '#248de9', borderWidth: 1.5 },
  checkbox: { width: 24, height: 24, borderRadius: 12, borderWidth: 2, borderColor: '#62b2ff', alignItems: 'center', justifyContent: 'center' },
  checkboxText: { color: '#62b2ff', fontSize: 14, fontWeight: '800' },
  selectToggle: { alignSelf: 'flex-end' },
  selectToggleText: { color: '#62b2ff', fontWeight: '700', fontSize: 13 },
  batchActions: { flexDirection: 'row', gap: 8, flexWrap: 'wrap' },
  batchBtn: { backgroundColor: '#1f4a37', padding: 10, borderRadius: 8 },
  batchBtnDanger: { backgroundColor: '#5a2633', padding: 10, borderRadius: 8 },
  batchBtnText: { color: '#fff', fontWeight: '700', fontSize: 12 },
  itemRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  itemInfo: { flex: 1 },
  name: { color: '#f1f7ff', fontWeight: '700' },
  meta: { color: '#9eb2c8', fontSize: 12, marginTop: 3 },
  error: { color: '#ff9aac', marginTop: 4, fontSize: 12 },
  link: { color: '#62b2ff', marginTop: 4, fontSize: 12, fontWeight: '700' },
  itemActions: { flexDirection: 'row', gap: 8, alignItems: 'center' },
  retryBtn: { color: '#f8c458', fontSize: 13, fontWeight: '800', paddingHorizontal: 6 },
  cancelBtn: { color: '#ff90a5', fontSize: 18, fontWeight: '800', paddingHorizontal: 8 },
  progressTrack: { height: 20, backgroundColor: '#0c1929', borderRadius: 10, marginTop: 6, overflow: 'hidden', position: 'relative' },
  progressFill: { height: '100%', backgroundColor: '#248de9', borderRadius: 10, position: 'absolute', left: 0, top: 0 },
  progressLabel: { color: '#fff', fontSize: 10, fontWeight: '800', position: 'absolute', alignSelf: 'center', top: 3 },
});
