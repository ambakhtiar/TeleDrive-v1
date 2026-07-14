import { useCallback, useEffect, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  Alert,
  TextInput,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';

import { createForumTopic, loadForumGroupsWithTopics, type ForumGroup } from '@/services/telegram';
import { listFolderSources, linkFolderToTopic } from '@/database/folders';
import type { FolderSource } from '@/database/types';

export default function TopicsScreen() {
  const router = useRouter();
  const [groups, setGroups] = useState<ForumGroup[]>([]);
  const [folders, setFolders] = useState<FolderSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [assigningFolder, setAssigningFolder] = useState<string | null>(null);
  const [expandedGroup, setExpandedGroup] = useState<number | null>(null);
  const [creatingInGroup, setCreatingInGroup] = useState<number | null>(null);
  const [newTopicName, setNewTopicName] = useState('');

  const loadData = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [forumGroups, savedFolders] = await Promise.all([
        loadForumGroupsWithTopics(),
        listFolderSources(),
      ]);
      setGroups(forumGroups);
      setFolders(savedFolders);
      if (forumGroups.length === 0) {
        setLoadError('No forum groups found. Make sure your Telegram account is signed in and has joined forum groups.');
      }
    } catch (error) {
      const msg = error instanceof Error ? error.message : '';
      if (msg.includes('not connected') || msg.includes('closed') || msg.includes('auth')) {
        setLoadError('Telegram is not connected. Go back to sign in first.');
      } else if (msg.includes('permission') || msg.includes('Permission')) {
        setLoadError('You do not have permission to view forum groups. Bot admin rights may be required.');
      } else {
        setLoadError(msg || 'Could not load forum groups.');
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  async function assignFolderToTopic(folderId: number, chatId: number, topicId: number) {
    try {
      await linkFolderToTopic(folderId, chatId, topicId);
      Alert.alert('Linked', 'Folder linked to topic');
      loadData();
    } catch (error) {
      const msg = error instanceof Error ? error.message : '';
      if (msg.includes('permission') || msg.includes('Permission') || msg.includes('RIGHTS')) {
        Alert.alert(
          'Permission denied',
          'Your account does not have permission to manage topics in this group. Contact the group admin for topic management rights.',
        );
      } else {
        Alert.alert('Failed to assign folder', msg || 'Unknown error.');
      }
    }
  }

  async function handleCreateTopic(chatId: number) {
    const name = newTopicName.trim();
    if (!name) {
      Alert.alert('Name required', 'Enter a topic name first.');
      return;
    }
    try {
      await createForumTopic(chatId, name);
      Alert.alert('Topic created', `"${name}" has been created.`);
      setCreatingInGroup(null);
      setNewTopicName('');
      loadData();
    } catch (error) {
      const msg = error instanceof Error ? error.message : '';
      Alert.alert('Failed to create topic', msg || 'Check your permissions in this group.');
    }
  }

  if (loading) {
    return (
      <SafeAreaView style={styles.loadingContainer}>
        <ActivityIndicator size="large" color="#49a7ff" />
        <Text style={styles.loadingText}>Loading Telegram groups...</Text>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      {/* Header */}
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} style={styles.backButton}>
          <Ionicons name="arrow-back" size={24} color="#e2e8f0" />
        </Pressable>
        <Text style={styles.title}>Forum Topics</Text>
      </View>

      <ScrollView style={styles.content}>
        {/* Error state */}
        {loadError && (
          <View style={styles.errorCard}>
            <Ionicons name="alert-circle" size={20} color="#f59e0b" />
            <Text style={styles.errorText}>{loadError}</Text>
            <Pressable onPress={() => loadData()} style={styles.retryBtn}>
              <Text style={styles.retryText}>Retry</Text>
            </Pressable>
          </View>
        )}

        {/* Folder assignments */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Folder → Topic Mapping</Text>
          {folders.map((folder) => {
            const matchedGroup = groups.find((g) => g.id === folder.chatId);
            const matchedTopic = matchedGroup?.topics.find((t) => t.id === folder.topicId);

            return (
              <View key={folder.id} style={styles.folderCard}>
                <View style={styles.folderInfo}>
                  <Ionicons name="folder" size={20} color="#49a7ff" />
                  <View style={styles.folderDetails}>
                    <Text style={styles.folderName}>{folder.displayName}</Text>
                    {matchedGroup && matchedTopic ? (
                      <Text style={styles.linkedTopic}>
                        {matchedGroup.title} → {matchedTopic.name}
                      </Text>
                    ) : (
                      <Text style={styles.unlinkedText}>No topic assigned</Text>
                    )}
                  </View>
                </View>
                <Pressable
                  style={styles.linkButton}
                  onPress={() => setAssigningFolder(assigningFolder === folder.treeUri ? null : folder.treeUri)}
                >
                  <Ionicons
                    name={matchedGroup ? 'link' : 'add-circle'}
                    size={20}
                    color={matchedGroup ? '#f59e0b' : '#49a7ff'}
                  />
                </Pressable>
              </View>
            );
          })}
        </View>

        {/* Forum groups */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Available Groups</Text>
          {groups.length === 0 && !loadError ? (
            <View style={styles.emptyCard}>
              <Ionicons name="chatbubbles-outline" size={24} color="#64748b" />
              <Text style={styles.emptyText}>No forum groups found. Create topics in Telegram first.</Text>
              <Text style={styles.emptyHint}>
                Forum groups require topics to be enabled in Telegram group settings.
              </Text>
            </View>
          ) : (
            groups.map((group) => (
              <View key={group.id} style={styles.groupCard}>
                <Pressable
                  style={styles.groupHeader}
                  onPress={() => setExpandedGroup(expandedGroup === group.id ? null : group.id)}
                >
                  <Ionicons name="chatbubbles" size={20} color="#49a7ff" />
                  <Text style={styles.groupName}>{group.title}</Text>
                  <Ionicons
                    name={expandedGroup === group.id ? 'chevron-up' : 'chevron-down'}
                    size={20}
                    color="#94a3b8"
                  />
                </Pressable>

                {expandedGroup === group.id && (
                  <View style={styles.topicsList}>
                    {group.topics.length === 0 ? (
                      <Text style={styles.noTopicsText}>No topics in this group</Text>
                    ) : (
                      group.topics.map((topic) => (
                        <Pressable
                          key={topic.id}
                          style={styles.topicItem}
                          onPress={() => {
                            if (assigningFolder) {
                              const folder = folders.find((f) => f.treeUri === assigningFolder);
                              if (folder) {
                                assignFolderToTopic(folder.id, group.id, topic.id);
                                setAssigningFolder(null);
                              }
                            }
                          }}
                        >
                          <View style={styles.topicInfo}>
                            <Text style={styles.topicName}># {topic.name}</Text>
                            <Text style={styles.topicMeta}>{topic.isGeneral ? 'General' : 'Topic'}</Text>
                          </View>
                          {assigningFolder && (
                            <Ionicons name="add-circle-outline" size={20} color="#49a7ff" />
                          )}
                        </Pressable>
                      ))
                    )}

                    {creatingInGroup === group.id ? (
                      <View style={styles.createTopicForm}>
                        <TextInput
                          value={newTopicName}
                          onChangeText={setNewTopicName}
                          placeholder="Topic name"
                          placeholderTextColor="#64748b"
                          style={styles.createTopicInput}
                          autoFocus
                        />
                        <View style={styles.createTopicActions}>
                          <Pressable
                            onPress={() => void handleCreateTopic(group.id)}
                            style={styles.createTopicConfirm}
                          >
                            <Ionicons name="checkmark" size={18} color="#fff" />
                            <Text style={styles.createTopicText}>Create</Text>
                          </Pressable>
                          <Pressable
                            onPress={() => { setCreatingInGroup(null); setNewTopicName(''); }}
                            style={styles.createTopicCancel}
                          >
                            <Text style={styles.createTopicCancelText}>Cancel</Text>
                          </Pressable>
                        </View>
                      </View>
                    ) : (
                      <Pressable
                        style={styles.createTopicButton}
                        onPress={() => { setCreatingInGroup(group.id); setNewTopicName(''); }}
                      >
                        <Ionicons name="add" size={18} color="#49a7ff" />
                        <Text style={styles.createTopicButtonText}>Create Topic</Text>
                      </Pressable>
                    )}
                  </View>
                )}
              </View>
            ))
          )}
        </View>

        {assigningFolder && groups.length > 0 && (
          <View style={styles.assignHint}>
            <Ionicons name="information-circle" size={16} color="#f59e0b" />
            <Text style={styles.assignHintText}>Tap a topic to assign the selected folder.</Text>
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#09121f' },
  loadingContainer: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#09121f' },
  loadingText: { color: '#94a3b8', marginTop: 12, fontSize: 14 },
  header: { flexDirection: 'row', alignItems: 'center', paddingTop: 48, paddingHorizontal: 20, paddingBottom: 16 },
  backButton: { padding: 8, marginRight: 12 },
  title: { color: '#e2e8f0', fontSize: 20, fontWeight: '700' },
  content: { flex: 1, paddingHorizontal: 20 },
  errorCard: { backgroundColor: '#3d2433', borderRadius: 12, padding: 14, gap: 8, marginBottom: 16, flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap' },
  errorText: { color: '#fbbf24', fontSize: 13, flex: 1, minWidth: 200 },
  retryBtn: { backgroundColor: '#f59e0b33', borderRadius: 8, paddingHorizontal: 12, paddingVertical: 6 },
  retryText: { color: '#f59e0b', fontWeight: '700', fontSize: 12 },
  section: { marginBottom: 24 },
  sectionTitle: { color: '#94a3b8', fontSize: 13, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 12 },
  folderCard: { flexDirection: 'row', alignItems: 'center', backgroundColor: '#1e293b', borderRadius: 12, padding: 14, marginBottom: 8 },
  folderInfo: { flexDirection: 'row', alignItems: 'center', flex: 1, gap: 12 },
  folderDetails: { flex: 1 },
  folderName: { color: '#e2e8f0', fontSize: 15, fontWeight: '600' },
  linkedTopic: { color: '#49a7ff', fontSize: 12, marginTop: 2 },
  unlinkedText: { color: '#94a3b8', fontSize: 12, marginTop: 2 },
  linkButton: { padding: 8 },
  groupCard: { backgroundColor: '#1e293b', borderRadius: 12, marginBottom: 8, overflow: 'hidden' },
  groupHeader: { flexDirection: 'row', alignItems: 'center', padding: 14, gap: 12 },
  groupName: { color: '#e2e8f0', fontSize: 15, fontWeight: '600', flex: 1 },
  topicsList: { paddingHorizontal: 14, paddingBottom: 12 },
  topicItem: { flexDirection: 'row', alignItems: 'center', paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: '#334155' },
  topicInfo: { flex: 1 },
  topicName: { color: '#e2e8f0', fontSize: 14 },
  topicMeta: { color: '#64748b', fontSize: 12, marginTop: 2 },
  noTopicsText: { color: '#64748b', fontSize: 13, paddingVertical: 8 },
  createTopicButton: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingVertical: 10, marginTop: 4 },
  createTopicButtonText: { color: '#49a7ff', fontWeight: '700', fontSize: 13 },
  createTopicForm: { backgroundColor: '#0c1929', borderRadius: 10, padding: 10, marginTop: 8, gap: 8 },
  createTopicInput: { backgroundColor: '#152840', color: '#fff', padding: 10, borderRadius: 8, fontSize: 14 },
  createTopicActions: { flexDirection: 'row', gap: 10, alignItems: 'center' },
  createTopicConfirm: { flexDirection: 'row', alignItems: 'center', gap: 4, backgroundColor: '#248de9', borderRadius: 8, paddingHorizontal: 14, paddingVertical: 8 },
  createTopicText: { color: '#fff', fontWeight: '700', fontSize: 13 },
  createTopicCancel: { paddingHorizontal: 10, paddingVertical: 8 },
  createTopicCancelText: { color: '#94a3b8', fontWeight: '600', fontSize: 13 },
  emptyCard: { backgroundColor: '#1e293b', borderRadius: 12, padding: 20, gap: 8, alignItems: 'center' },
  emptyText: { color: '#64748b', fontSize: 13, textAlign: 'center' },
  emptyHint: { color: '#475569', fontSize: 12, textAlign: 'center', marginTop: 4 },
  assignHint: { flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: '#2a2a1e', borderRadius: 10, padding: 12, marginBottom: 24 },
  assignHintText: { color: '#f59e0b', fontSize: 13, flex: 1 },
});
