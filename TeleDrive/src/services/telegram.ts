import { createForumTopic as tdlibCreateTopic, loadForumGroups, getForumTopics as fetchForumTopics } from '@/services/tdlib';

export interface ForumTopic {
  id: number;
  name: string;
  isGeneral: boolean;
  messageCount: number;
}

export interface ForumGroup {
  id: number;
  title: string;
  type: string;
  topics: ForumTopic[];
}

/**
 * Create a new forum topic in a group.
 */
export async function createForumTopic(chatId: number, name: string): Promise<ForumTopic> {
  const topic = await tdlibCreateTopic(chatId, name);
  return {
    id: topic.topicId,
    name: topic.name,
    isGeneral: false,
    messageCount: 0,
  };
}

/**
 * Load all forum groups with their topics.
 */
export async function loadForumGroupsWithTopics(): Promise<ForumGroup[]> {
  const groups = await loadForumGroups();

  const groupsWithTopics = await Promise.all(
    groups.map(async (group) => {
      try {
        const topics = await fetchForumTopics(group.chatId);
        return {
          id: group.chatId,
          title: group.title,
          type: group.type,
          topics: topics.map((t) => ({
            id: t.topicId,
            name: t.name,
            isGeneral: t.isGeneral,
            messageCount: 0,
          })),
        };
      } catch {
        return {
          id: group.chatId,
          title: group.title,
          type: group.type,
          topics: [],
        };
      }
    }),
  );

  return groupsWithTopics;
}
