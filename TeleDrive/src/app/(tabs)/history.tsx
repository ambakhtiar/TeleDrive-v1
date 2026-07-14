import React, { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Alert, FlatList, Linking, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { initializeDatabase } from '@/database/client';
import type { FolderSource, UploadQueueItem } from '@/database/types';
import { type StatusFilter, type SortField, type SortOrder, listUploadedFiles, listAllUploadedFiles } from '@/database/uploads';
import { listDailySummaries, type DaySummary } from '@/database/dashboard';
import { listFolderSources } from '@/database/folders';
import { uploadsToCsv } from '@/utils/csv';
import { formatBytes } from '@/utils/format';
import { File, Paths } from 'expo-file-system';

const SORT_OPTIONS: { label: string; value: SortField }[] = [
  { label: 'Date', value: 'date' },
  { label: 'Name', value: 'name' },
  { label: 'Size', value: 'size' },
];

const STATUS_OPTIONS: { label: string; value: StatusFilter }[] = [
  { label: 'Uploaded', value: 'success' },
  { label: 'Failed', value: 'failed' },
  { label: 'Pending', value: 'pending' },
  { label: 'All', value: 'all' },
];

export default function HistoryScreen() {
  const [search, setSearch] = useState('');
  const [items, setItems] = useState<UploadQueueItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [hasMore, setHasMore] = useState(false);
  const [sortField, setSortField] = useState<SortField>('date');
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('success');
  const [sourceFilter, setSourceFilter] = useState<number | null>(null);
  const [allFolders, setAllFolders] = useState<(FolderSource & { fileCount?: number })[]>([]);
  const [showFolderPicker, setShowFolderPicker] = useState(false);

  const load = useCallback(async (offset = 0) => {
    setLoading(true);
    await initializeDatabase();
    if (allFolders.length === 0) {
      setAllFolders(await listFolderSources());
    }
    const next = await listUploadedFiles(search, offset, sortField, sortOrder, statusFilter, sourceFilter);
    setItems((current) => offset === 0 ? next : [...current, ...next]);
    setHasMore(next.length === 20);
    setLoading(false);
  }, [search, sortField, sortOrder, statusFilter, sourceFilter, allFolders.length]);

  useEffect(() => {
    void load();
  }, [load]);

  const exportCsv = async () => {
    try {
      const allItems = await listAllUploadedFiles(search, statusFilter, sourceFilter);
      if (allItems.length === 0) {
        Alert.alert('No data', 'No files to export.');
        return;
      }
      const csv = uploadsToCsv(allItems);
      const file = new File(Paths.cache, `teledrive_history_${Date.now()}.csv`);
      const encoder = new TextEncoder();
      const writable = file.writableStream();
      const writer = writable.getWriter();
      await writer.write(encoder.encode(csv));
      await writer.close();
      Alert.alert('Exported', `Saved ${allItems.length} rows to cache.`);
    } catch (error) {
      Alert.alert('Export failed', error instanceof Error ? error.message : 'Could not export history.');
    }
  };

  const toggleSortOrder = () => {
    setSortOrder((prev) => prev === 'desc' ? 'asc' : 'desc');
  };

  const openTelegramLink = useCallback((link: string) => {
    const url = link.startsWith('http') ? link : `https://t.me/${link}`;
    Linking.openURL(url).catch(() => {
      Alert.alert('Could not open link', 'Telegram may not be installed.');
    });
  }, []);

  const [dailySummaries, setDailySummaries] = useState<DaySummary[]>([]);
  const [showReports, setShowReports] = useState(false);

  const toggleReports = async () => {
    if (showReports) {
      setShowReports(false);
      return;
    }
    const summaries = await listDailySummaries(14);
    setDailySummaries(summaries);
    setShowReports(true);
  };

  const renderItem = useCallback(({ item }: { item: UploadQueueItem }) => (
    <HistoryItem item={item} onOpenLink={openTelegramLink} />
  ), [openTelegramLink]);

  const ListFooter = hasMore || items.length > 0 ? (
    <>
      {hasMore && (
        <Pressable onPress={() => void load(items.length)} style={styles.more}>
          <Text style={styles.moreText}>Load more</Text>
        </Pressable>
      )}
      {items.length > 0 && (
        <Pressable onPress={() => void exportCsv()} style={styles.exportButton}>
          <Text style={styles.exportText}>Export CSV</Text>
        </Pressable>
      )}
    </>
  ) : null;

  return (
    <SafeAreaView style={styles.safe}>
      <FlatList
        data={items}
        keyExtractor={(item) => String(item.id)}
        renderItem={renderItem}
        contentContainerStyle={styles.content}
        ListHeaderComponent={
          <>
            <Text style={styles.title}>History</Text>

            <TextInput
              value={search}
              onChangeText={setSearch}
              placeholder="Search filename"
              placeholderTextColor="#8299b1"
              style={styles.input}
            />

            <View style={styles.filterRow}>
              {STATUS_OPTIONS.map((opt) => (
                <Pressable
                  key={opt.value}
                  onPress={() => { setStatusFilter(opt.value); }}
                  style={[styles.filterPill, statusFilter === opt.value && styles.filterActive]}
                >
                  <Text style={[styles.filterText, statusFilter === opt.value && styles.filterTextActive]}>
                    {opt.label}
                  </Text>
                </Pressable>
              ))}
            </View>

            <View style={styles.filterRow}>
              {SORT_OPTIONS.map((opt) => (
                <Pressable
                  key={opt.value}
                  onPress={() => { setSortField(opt.value); }}
                  style={[styles.filterPill, sortField === opt.value && styles.filterActive]}
                >
                  <Text style={[styles.filterText, sortField === opt.value && styles.filterTextActive]}>
                    {opt.label}
                  </Text>
                </Pressable>
              ))}
              <Pressable onPress={toggleSortOrder} style={styles.filterPill}>
                <Text style={styles.filterText}>{sortOrder === 'desc' ? '↓' : '↑'}</Text>
              </Pressable>
            </View>

            <View style={styles.filterRow}>
              <Pressable
                onPress={() => setShowFolderPicker(!showFolderPicker)}
                style={[styles.filterPill, showFolderPicker && styles.filterActive]}
              >
                <Text style={[styles.filterText, showFolderPicker && styles.filterTextActive]}>
                  {sourceFilter == null ? 'All folders' : allFolders.find((f) => f.id === sourceFilter)?.displayName ?? 'Folder'}
                </Text>
              </Pressable>
            </View>

            {showFolderPicker && (
              <View style={styles.folderPickerCard}>
                <Pressable
                  onPress={() => { setSourceFilter(null); setShowFolderPicker(false); }}
                  style={[styles.folderOption, sourceFilter == null && styles.folderOptionActive]}
                >
                  <Text style={[styles.folderOptionText, sourceFilter == null && styles.folderOptionTextActive]}>All folders</Text>
                </Pressable>
                {allFolders.map((f) => (
                  <Pressable
                    key={f.id}
                    onPress={() => { setSourceFilter(f.id); setShowFolderPicker(false); }}
                    style={[styles.folderOption, sourceFilter === f.id && styles.folderOptionActive]}
                  >
                    <Text style={[styles.folderOptionText, sourceFilter === f.id && styles.folderOptionTextActive]}>
                      {f.displayName}
                    </Text>
                  </Pressable>
                ))}
              </View>
            )}

            <Pressable onPress={() => void toggleReports()} style={styles.reportsToggle}>
              <Text style={styles.reportsToggleText}>{showReports ? 'Hide daily reports' : 'Show daily reports'}</Text>
            </Pressable>

            {showReports && (
              <View style={styles.reportsSection}>
                {dailySummaries.length === 0 ? (
                  <Text style={styles.reportEmpty}>No uploads yet.</Text>
                ) : (
                  dailySummaries.map((s) => (
                    <View key={s.day} style={styles.reportRow}>
                      <Text style={styles.reportDay}>{s.day}</Text>
                      <Text style={styles.reportStats}>{s.fileCount} files · {formatBytes(s.totalBytes)}</Text>
                    </View>
                  ))
                )}
              </View>
            )}
          </>
        }
        ListEmptyComponent={
          loading ? (
            <ActivityIndicator color="#49a7ff" />
          ) : (
            <View style={styles.card}>
              <Text style={styles.name}>No files found</Text>
              <Text style={styles.meta}>Try changing filters or uploading some files first.</Text>
            </View>
          )
        }
        ListFooterComponent={ListFooter}
      />
    </SafeAreaView>
  );
}

const HistoryItem = React.memo(function HistoryItem({ item, onOpenLink }: { item: UploadQueueItem; onOpenLink: (link: string) => void }) {
  return (
    <View style={styles.card}>
      <Text numberOfLines={1} style={styles.name}>{item.filename}</Text>
      <Text style={styles.meta}>
        {formatBytes(item.fileSize)} · {new Date(item.updatedAt).toLocaleDateString()}
        {item.status !== 'success' ? ` · ${item.status}` : ''}
      </Text>
      {item.errorMessage ? (
        <Text style={styles.error}>{item.errorMessage}</Text>
      ) : null}
      {item.telegramMessageLink ? (
        <Pressable onPress={() => onOpenLink(item.telegramMessageLink!)}>
          <Text style={styles.link}>View on Telegram</Text>
        </Pressable>
      ) : null}
    </View>
  );
});

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#09121f' },
  content: { padding: 20, gap: 14, paddingBottom: 40 },
  title: { color: '#fff', fontSize: 28, fontWeight: '800' },
  input: { backgroundColor: '#152840', color: '#fff', padding: 14, borderRadius: 12 },
  filterRow: { flexDirection: 'row', gap: 8, flexWrap: 'wrap' },
  filterPill: { backgroundColor: '#172a40', borderRadius: 8, paddingHorizontal: 12, paddingVertical: 7 },
  filterActive: { backgroundColor: '#248de9' },
  filterText: { color: '#b3c6db', fontSize: 13, fontWeight: '600' },
  filterTextActive: { color: '#fff' },
  folderPickerCard: { backgroundColor: '#101e30', borderRadius: 12, padding: 8, gap: 4 },
  folderOption: { borderRadius: 8, paddingHorizontal: 12, paddingVertical: 8 },
  folderOptionActive: { backgroundColor: '#248de9' },
  folderOptionText: { color: '#b3c6db', fontWeight: '600', fontSize: 13 },
  folderOptionTextActive: { color: '#fff' },
  reportsToggle: { backgroundColor: '#152840', padding: 12, borderRadius: 10, alignItems: 'center' },
  reportsToggleText: { color: '#62b2ff', fontWeight: '700', fontSize: 13 },
  reportsSection: { backgroundColor: '#101e30', borderRadius: 14, padding: 14, gap: 8 },
  reportEmpty: { color: '#9eb2c8' },
  reportRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  reportDay: { color: '#eff7ff', fontWeight: '700', fontSize: 14 },
  reportStats: { color: '#58d68d', fontWeight: '600', fontSize: 13 },
  card: { backgroundColor: '#101e30', padding: 16, borderRadius: 16, gap: 4 },
  name: { color: '#f1f7ff', fontWeight: '700' },
  meta: { color: '#9eb2c8' },
  error: { color: '#ff8a9a', fontSize: 12, marginTop: 4 },
  link: { color: '#62b2ff', fontWeight: '700', fontSize: 12, marginTop: 4 },
  more: { padding: 14, alignItems: 'center' },
  moreText: { color: '#62b2ff', fontWeight: '800' },
  exportButton: { backgroundColor: '#1f4a37', padding: 14, borderRadius: 12, alignItems: 'center' },
  exportText: { color: '#58d68d', fontWeight: '800' },
});
