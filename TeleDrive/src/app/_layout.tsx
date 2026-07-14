import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import '@/global.css';

import { AuthProvider } from '@/providers/AuthProvider';
import { ErrorBoundary } from '@/components/ErrorBoundary';

export default function RootLayout() {
  return (
    <ErrorBoundary>
      <AuthProvider>
        <StatusBar style="light" />
        <Stack screenOptions={{ headerShown: false, animation: 'fade' }}>
          <Stack.Screen name="(tabs)" />
          <Stack.Screen name="onboarding" />
          <Stack.Screen name="folders" />
          <Stack.Screen name="routing" />
          <Stack.Screen name="topics" />
        </Stack>
      </AuthProvider>
    </ErrorBoundary>
  );
}
