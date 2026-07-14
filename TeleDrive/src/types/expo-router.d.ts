// Temporary module declaration while expo-router v57 ships without .d.ts files
declare module 'expo-router' {
  export function useRouter(): {
    replace: (href: string) => void;
    push: (href: string) => void;
    back: () => void;
    navigate: (href: string) => void;
  };
  export function useSegments(): string[];
  export function useLocalSearchParams(): Record<string, string | undefined>;
  export function useGlobalSearchParams(): Record<string, string | undefined>;

  export type Href = string | { pathname: string; params?: Record<string, any> };

  export const Link: React.ComponentType<any>;
  export const Redirect: React.ComponentType<any>;
  export const Stack: any;
  export const Tabs: any;
  export const Slot: React.ComponentType<any>;
  export const Router: React.ComponentType<any>;

  export function useFocusEffect(effect: () => void | (() => void)): void;
  export function useNavigation(): any;
  export function useRoute(): any;
  export function useNavigationContainerRef(): any;

  export const ExpoRoot: React.ComponentType<any>;
  export const Unmatched: React.ComponentType<any>;
}
