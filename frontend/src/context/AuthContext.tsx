import { useEffect, useState, useCallback } from 'react';
import type { ReactNode } from 'react';
import {
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut as firebaseSignOut,
  onAuthStateChanged,
} from 'firebase/auth';
import type { User as FirebaseUser } from 'firebase/auth';
import { auth, googleAuthProvider, isFirebaseConfigured } from '../lib/firebase';
import { apiClient } from '../lib/apiClient';
import { AuthContext, DEMO_SESSION_KEY } from './authContextDef';
import type { AppUser } from './authContextDef';
import {
  resolveUserRole,
  mapFirebaseError,
  createDemoGoogleUser,
  createDemoEmailUser,
} from './authUtils';

function getInitialDemoUser(): AppUser | null {
  if (typeof window === 'undefined') return null;
  try {
    const stored = sessionStorage.getItem(DEMO_SESSION_KEY);
    return stored ? (JSON.parse(stored) as AppUser) : null;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const isConfigured = isFirebaseConfigured();
  const [user, setUser] = useState<AppUser | null>(() => {
    if (import.meta.env.DEV) {
      const demo = getInitialDemoUser();
      if (demo) return demo;
    }
    return !isConfigured ? getInitialDemoUser() : null;
  });
  const [firebaseUser, setFirebaseUser] = useState<FirebaseUser | null>(null);
  const [loading, setLoading] = useState<boolean>(() => {
    if (import.meta.env.DEV && getInitialDemoUser()) {
      return false;
    }
    return isConfigured;
  });
  const [error, setError] = useState<string | null>(null);

  // Listen to Firebase auth state changes when configured
  useEffect(() => {
    if (!isConfigured || !auth) {
      return;
    }

    const unsubscribe = onAuthStateChanged(auth, async (fbUser) => {
      if (import.meta.env.DEV && getInitialDemoUser()) {
        setLoading(false);
        return;
      }
      setFirebaseUser(fbUser);
      if (fbUser) {
        let claims: Record<string, unknown> | undefined;
        try {
          const tokenResult = await fbUser.getIdTokenResult();
          claims = tokenResult.claims as Record<string, unknown>;
        } catch {
          claims = undefined;
        }

        const role = resolveUserRole(fbUser.email, claims);

        setUser({
          uid: fbUser.uid,
          email: fbUser.email,
          displayName: fbUser.displayName || fbUser.email?.split('@')[0] || 'Operator',
          role,
          isDemoUser: false,
        });
      } else {
        setUser(null);
      }
      setLoading(false);
    });

    return () => unsubscribe();
  }, [isConfigured]);

  const signIn = async (email: string, pass: string): Promise<void> => {
    setError(null);
    setLoading(true);

    try {
      if (isConfigured && auth) {
        await signInWithEmailAndPassword(auth, email, pass);
      } else {
        // Simulated local authentication when Firebase environment variables are not set
        await new Promise((resolve) => setTimeout(resolve, 500));
        const demoUser = createDemoEmailUser(email);
        sessionStorage.setItem(DEMO_SESSION_KEY, JSON.stringify(demoUser));
        setUser(demoUser);
      }
    } catch (err: unknown) {
      const errObject = err as { code?: string; message?: string };
      const friendlyMessage = errObject.code
        ? mapFirebaseError(errObject.code)
        : errObject.message || 'Failed to authenticate.';
      setError(friendlyMessage);
      throw new Error(friendlyMessage);
    } finally {
      setLoading(false);
    }
  };

  const signInWithGoogle = async (): Promise<void> => {
    setError(null);
    setLoading(true);

    try {
      if (isConfigured && auth) {
        await signInWithPopup(auth, googleAuthProvider);
      } else {
        // Simulated Google authentication for demo mode
        await new Promise((resolve) => setTimeout(resolve, 500));
        const demoUser = createDemoGoogleUser();
        sessionStorage.setItem(DEMO_SESSION_KEY, JSON.stringify(demoUser));
        setUser(demoUser);
      }
    } catch (err: unknown) {
      const errObject = err as { code?: string; message?: string };
      const friendlyMessage = errObject.code
        ? mapFirebaseError(errObject.code)
        : errObject.message || 'Failed to authenticate with Google.';
      setError(friendlyMessage);
      throw new Error(friendlyMessage);
    } finally {
      setLoading(false);
    }
  };

  const signOut = async (): Promise<void> => {
    setError(null);
    setLoading(true);

    try {
      if (isConfigured && auth) {
        await firebaseSignOut(auth);
      }
      sessionStorage.removeItem(DEMO_SESSION_KEY);
      setUser(null);
      setFirebaseUser(null);
    } catch (err: unknown) {
      const errObject = err as { message?: string };
      setError(errObject.message || 'Failed to sign out.');
    } finally {
      setLoading(false);
    }
  };

  const getIdToken = useCallback(
    async (forceRefresh: boolean = false): Promise<string | null> => {
      if (isConfigured && auth) {
        if (typeof auth.authStateReady === 'function') {
          try {
            await auth.authStateReady();
          } catch {
            // Proceed to current user evaluation
          }
        }
        const currentUser = auth.currentUser || firebaseUser;
        if (currentUser) {
          try {
            return await currentUser.getIdToken(forceRefresh);
          } catch {
            return null;
          }
        }
        return null;
      }
      if (user?.isDemoUser) {
        return `mock_dev_token_${user.uid}_expires_${Date.now() + 3600000}`;
      }
      return null;
    },
    [isConfigured, firebaseUser, user]
  );

  // Synchronously ensure apiClient always has the token provider bound
  useEffect(() => {
    apiClient.setTokenProvider(getIdToken);
  }, [getIdToken]);

  const clearError = () => setError(null);

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        error,
        isConfigured,
        signIn,
        signInWithGoogle,
        signOut,
        getIdToken,
        clearError,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

