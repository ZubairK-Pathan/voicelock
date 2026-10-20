import { createContext } from 'react';

export interface AppUser {
  uid: string;
  email: string | null;
  displayName: string | null;
  role: 'admin' | 'user';
  isDemoUser?: boolean;
}

export interface AuthContextType {
  user: AppUser | null;
  loading: boolean;
  error: string | null;
  isConfigured: boolean;
  signIn: (email: string, pass: string) => Promise<void>;
  signInWithGoogle: () => Promise<void>;
  signOut: () => Promise<void>;
  getIdToken: (forceRefresh?: boolean) => Promise<string | null>;
  clearError: () => void;
}

export const AuthContext = createContext<AuthContextType | undefined>(undefined);
export const DEMO_SESSION_KEY = 'voicelock_demo_user_session';
