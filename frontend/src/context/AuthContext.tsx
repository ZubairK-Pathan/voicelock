import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import {
  signInWithEmailAndPassword,
  signOut as firebaseSignOut,
  onAuthStateChanged,
} from 'firebase/auth';
import type { User as FirebaseUser } from 'firebase/auth';
import { auth, isFirebaseConfigured } from '../lib/firebase';
import { AuthContext, DEMO_SESSION_KEY } from './authContextDef';
import type { AppUser } from './authContextDef';

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
    return !isConfigured ? getInitialDemoUser() : null;
  });
  const [firebaseUser, setFirebaseUser] = useState<FirebaseUser | null>(null);
  const [loading, setLoading] = useState<boolean>(() => isConfigured);
  const [error, setError] = useState<string | null>(null);

  // Listen to Firebase auth state changes when configured
  useEffect(() => {
    if (!isConfigured || !auth) {
      return;
    }

    const unsubscribe = onAuthStateChanged(auth, async (fbUser) => {
      setFirebaseUser(fbUser);
      if (fbUser) {
        let role: 'admin' | 'user' = 'user';
        try {
          const tokenResult = await fbUser.getIdTokenResult();
          if (tokenResult.claims.admin === true || tokenResult.claims.role === 'admin') {
            role = 'admin';
          } else if (fbUser.email?.includes('admin')) {
            role = 'admin';
          }
        } catch {
          role = fbUser.email?.includes('admin') ? 'admin' : 'user';
        }

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

  const mapFirebaseError = (errCode: string): string => {
    switch (errCode) {
      case 'auth/invalid-credential':
      case 'auth/wrong-password':
      case 'auth/user-not-found':
        return 'Invalid email or password. Please verify your credentials.';
      case 'auth/invalid-email':
        return 'Please enter a valid operator email address.';
      case 'auth/user-disabled':
        return 'This operator account has been suspended or revoked.';
      case 'auth/too-many-requests':
        return 'Access temporarily blocked due to multiple failed attempts. Please retry later.';
      case 'auth/network-request-failed':
        return 'Network connection failed. Verify server and internet connectivity.';
      default:
        return 'Authentication failed. Please verify credentials or check project settings.';
    }
  };

  const signIn = async (email: string, pass: string): Promise<void> => {
    setError(null);
    setLoading(true);

    try {
      if (isConfigured && auth) {
        await signInWithEmailAndPassword(auth, email, pass);
      } else {
        // Simulated local authentication when Firebase environment variables are not set
        await new Promise((resolve) => setTimeout(resolve, 500));

        const normalizedEmail = email.trim().toLowerCase();
        const isAdmin = normalizedEmail.includes('admin') || normalizedEmail.includes('zubair');

        const demoUser: AppUser = {
          uid: `demo_usr_${Math.random().toString(36).substring(2, 10)}`,
          email: normalizedEmail,
          displayName: normalizedEmail.split('@')[0],
          role: isAdmin ? 'admin' : 'user',
          isDemoUser: true,
        };

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

  const getIdToken = async (forceRefresh: boolean = false): Promise<string | null> => {
    if (isConfigured && firebaseUser) {
      return await firebaseUser.getIdToken(forceRefresh);
    }
    if (user?.isDemoUser) {
      return `mock_dev_token_${user.uid}_expires_${Date.now() + 3600000}`;
    }
    return null;
  };

  const clearError = () => setError(null);

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        error,
        isConfigured,
        signIn,
        signOut,
        getIdToken,
        clearError,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
