import Constants from 'expo-constants';
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { useRouter, useSegments } from 'expo-router';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import { initTdLib, type AuthState, getAuthState, onAuthStateChanged } from '@/services/tdlib';

interface AuthContextValue {
  authState: AuthState;
  isLoading: boolean;
}

const AuthContext = createContext<AuthContextValue>({ authState: 'closed', isLoading: true });

export function useAuth(): AuthContextValue {
  return useContext(AuthContext);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [authState, setAuthState] = useState<AuthState>('closed');
  const [isLoading, setIsLoading] = useState(true);
  const [initError, setInitError] = useState<string | null>(null);
  const initRef = useRef(false);
  const router = useRouter();
  const segments = useSegments();

  const doInit = useCallback(() => {
    setInitError(null);
    const apiId = Number(Constants.expoConfig?.extra?.teledriveApiId) || 0;
    const apiHash = String(Constants.expoConfig?.extra?.teledriveApiHash || '');
    if (apiId && apiHash) {
      initTdLib(apiId, apiHash).catch((err) => {
        setInitError(err instanceof Error ? err.message : 'Failed to initialize Telegram library');
      });
    } else {
      setInitError('TELEDRIVE_API_ID and TELEDRIVE_API_HASH not set in environment');
    }
  }, []);

  useEffect(() => {
    const initialState = getAuthState();

    if (!initRef.current) {
      initRef.current = true;
      doInit();
    }

    setAuthState(initialState);
    setIsLoading(false);

    const unsub = onAuthStateChanged((state: AuthState) => {
      setAuthState(state);
    });

    return unsub;
  }, [doInit]);

  useEffect(() => {
    if (isLoading) return;

    const inAuthGroup = segments[0] === 'onboarding';

    if (authState !== 'ready' && !inAuthGroup) {
      router.replace('/onboarding');
    } else if (authState === 'ready' && inAuthGroup) {
      router.replace('/');
    }
  }, [authState, isLoading, segments, router]);

  if (initError) {
    return (
      <View style={styles.container}>
        <Text style={styles.errorTitle}>Initialization failed</Text>
        <Text style={styles.errorMessage}>{initError}</Text>
        <Pressable style={styles.retryButton} onPress={doInit}>
          <Text style={styles.retryText}>Retry</Text>
        </Pressable>
      </View>
    );
  }

  if (isLoading) {
    return (
      <View style={styles.container}>
        <ActivityIndicator color="#49a7ff" size="large" />
      </View>
    );
  }

  return (
    <AuthContext.Provider value={{ authState, isLoading }}>
      {children}
    </AuthContext.Provider>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#09121f', justifyContent: 'center', alignItems: 'center', padding: 24, gap: 12 },
  errorTitle: { color: '#ff5c7c', fontSize: 18, fontWeight: '800' },
  errorMessage: { color: '#b6c7dc', textAlign: 'center', lineHeight: 22 },
  retryButton: { backgroundColor: '#248de9', paddingHorizontal: 24, paddingVertical: 12, borderRadius: 10, marginTop: 8 },
  retryText: { color: '#fff', fontWeight: '800', fontSize: 15 },
});
