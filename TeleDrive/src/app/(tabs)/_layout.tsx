import { Tabs } from 'expo-router';
import { MaterialIcons } from '@expo/vector-icons';

const TAB_ICONS = {
  index: 'home' as const,
  queue: 'file-upload' as const,
  history: 'history' as const,
  settings: 'settings' as const,
};

type IconProps = { color: string; size: number };

export default function TabLayout() {
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: '#248de9',
        tabBarInactiveTintColor: '#91a6bf',
        tabBarStyle: {
          backgroundColor: '#09121f',
          borderTopColor: '#1a2d42',
          borderTopWidth: 1,
          height: 60,
          paddingBottom: 8,
          paddingTop: 8,
        },
        tabBarLabelStyle: {
          fontSize: 12,
          fontWeight: '600',
        },
      }}>
      <Tabs.Screen
        name="index"
        options={{
          title: 'Home',
          tabBarIcon: ({ color, size }: IconProps) => (
            <MaterialIcons name={TAB_ICONS.index} size={size} color={color} />
          ),
        }}
      />
      <Tabs.Screen
        name="queue"
        options={{
          title: 'Queue',
          tabBarIcon: ({ color, size }: IconProps) => (
            <MaterialIcons name={TAB_ICONS.queue} size={size} color={color} />
          ),
        }}
      />
      <Tabs.Screen
        name="history"
        options={{
          title: 'History',
          tabBarIcon: ({ color, size }: IconProps) => (
            <MaterialIcons name={TAB_ICONS.history} size={size} color={color} />
          ),
        }}
      />
      <Tabs.Screen
        name="settings"
        options={{
          title: 'Settings',
          tabBarIcon: ({ color, size }: IconProps) => (
            <MaterialIcons name={TAB_ICONS.settings} size={size} color={color} />
          ),
        }}
      />
    </Tabs>
  );
}
