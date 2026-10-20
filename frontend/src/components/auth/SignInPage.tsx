import React, { useState } from 'react';
import {
  Shield,
  Lock,
  Mail,
  Eye,
  EyeOff,
  AlertCircle,
  CheckCircle2,
  HelpCircle,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { useAuth } from '../../context/useAuth';

export const SignInPage: React.FC = () => {
  const { signIn, signInWithGoogle, loading, error, isConfigured, clearError } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [showSetupGuide, setShowSetupGuide] = useState(false);
  const [formValidation, setFormValidation] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    clearError();
    setFormValidation(null);

    const trimmedEmail = email.trim();
    if (!trimmedEmail) {
      setFormValidation('Please enter your operator email address.');
      return;
    }

    if (!trimmedEmail.includes('@') || !trimmedEmail.includes('.')) {
      setFormValidation('Please enter a valid email format (e.g. operator@voicelock.internal).');
      return;
    }

    if (!password) {
      setFormValidation('Please enter your password.');
      return;
    }

    if (password.length < 6) {
      setFormValidation('Password must be at least 6 characters.');
      return;
    }

    try {
      await signIn(trimmedEmail, password);
    } catch {
      // Error handled by AuthContext and displayed in error banner
    }
  };

  const handleGoogleSignIn = async () => {
    clearError();
    setFormValidation(null);
    try {
      await signInWithGoogle();
    } catch {
      // Error handled by AuthContext and displayed in error banner
    }
  };

  const handleUseDemoAccount = (demoEmail: string) => {
    setEmail(demoEmail);
    setPassword('VoiceLock2026!');
    clearError();
    setFormValidation(null);
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        width: '100%',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'radial-gradient(ellipse at 50% 20%, rgba(29, 78, 216, 0.15) 0%, #080C14 70%)',
        padding: '24px',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {/* Background Decorative Rings */}
      <div
        style={{
          position: 'absolute',
          width: '600px',
          height: '600px',
          borderRadius: '50%',
          border: '1px solid rgba(59, 130, 246, 0.08)',
          pointerEvents: 'none',
        }}
      />
      <div
        style={{
          position: 'absolute',
          width: '900px',
          height: '900px',
          borderRadius: '50%',
          border: '1px solid rgba(59, 130, 246, 0.04)',
          pointerEvents: 'none',
        }}
      />

      <div
        style={{
          maxWidth: '440px',
          width: '100%',
          background: 'rgba(14, 20, 34, 0.85)',
          backdropFilter: 'blur(16px)',
          WebkitBackdropFilter: 'blur(16px)',
          border: '1px solid rgba(255, 255, 255, 0.1)',
          borderRadius: 'var(--radius-lg)',
          boxShadow: '0 20px 50px -10px rgba(0, 0, 0, 0.7), 0 0 25px rgba(59, 130, 246, 0.15)',
          padding: '36px 32px',
          zIndex: 10,
        }}
      >
        {/* Brand Header */}
        <div style={{ textAlign: 'center', marginBottom: '28px' }}>
          <div
            style={{
              width: '48px',
              height: '48px',
              borderRadius: 'var(--radius-md)',
              background: 'linear-gradient(135deg, #1D4ED8 0%, #3B82F6 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              margin: '0 auto 14px',
              boxShadow: '0 0 20px rgba(59, 130, 246, 0.4)',
            }}
          >
            <Shield size={26} color="#FFFFFF" />
          </div>
          <h1 className="text-2xl font-bold text-primary" style={{ letterSpacing: '-0.02em' }}>
            VoiceLock Enterprise
          </h1>
          <p className="text-xs text-muted font-mono" style={{ marginTop: '4px', letterSpacing: '0.06em' }}>
            BIOMETRIC ACCESS CONTROL CONSOLE
          </p>
        </div>

        {/* Configuration Notice / Demo Mode Indicator */}
        {!isConfigured && (
          <div
            style={{
              padding: '10px 14px',
              background: 'rgba(245, 158, 11, 0.1)',
              border: '1px solid rgba(245, 158, 11, 0.25)',
              borderRadius: 'var(--radius-sm)',
              marginBottom: '20px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <HelpCircle size={15} color="#FBBF24" />
              <span className="text-xs font-semibold" style={{ color: '#FBBF24' }}>
                Development Demonstration Mode
              </span>
            </div>
            <p className="text-xs text-secondary" style={{ marginTop: '4px', lineHeight: '1.4' }}>
              Firebase Web credentials not configured in <code>.env.local</code>. Click a preset account below or enter any credentials to test the dashboard.
            </p>
            <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
              <button
                type="button"
                onClick={() => handleUseDemoAccount('admin@voicelock.internal')}
                className="btn btn-secondary"
                style={{ fontSize: '11px', padding: '3px 8px' }}
              >
                Admin Operator
              </button>
              <button
                type="button"
                onClick={() => handleUseDemoAccount('zubair@voicelock.internal')}
                className="btn btn-secondary"
                style={{ fontSize: '11px', padding: '3px 8px' }}
              >
                Zubair (User)
              </button>
              <button
                type="button"
                onClick={() => handleGoogleSignIn()}
                className="btn btn-secondary"
                style={{ fontSize: '11px', padding: '3px 8px', borderColor: 'rgba(59, 130, 246, 0.4)' }}
              >
                Google Demo (Admin)
              </button>
            </div>
          </div>
        )}

        {/* Error Banners */}
        {(error || formValidation) && (
          <div
            style={{
              padding: '12px 14px',
              background: 'rgba(239, 68, 68, 0.12)',
              border: '1px solid rgba(239, 68, 68, 0.3)',
              borderRadius: 'var(--radius-sm)',
              marginBottom: '20px',
              display: 'flex',
              gap: '10px',
              alignItems: 'flex-start',
            }}
            role="alert"
          >
            <AlertCircle size={16} color="#F87171" style={{ flexShrink: 0, marginTop: '2px' }} />
            <span className="text-xs text-primary" style={{ lineHeight: '1.4' }}>
              {formValidation || error}
            </span>
          </div>
        )}

        {/* Google Authentication Action */}
        <div style={{ marginBottom: '20px' }}>
          <button
            type="button"
            onClick={handleGoogleSignIn}
            disabled={loading}
            className="btn btn-secondary"
            style={{
              width: '100%',
              padding: '11px 16px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '10px',
              fontSize: '13px',
              fontWeight: 600,
              background: 'rgba(255, 255, 255, 0.04)',
              border: '1px solid rgba(255, 255, 255, 0.14)',
              color: '#F8FAFC',
              borderRadius: 'var(--radius-sm)',
              cursor: loading ? 'not-allowed' : 'pointer',
              transition: 'all 0.15s ease',
            }}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
              <path
                fill="#4285F4"
                d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
              />
              <path
                fill="#34A853"
                d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
              />
              <path
                fill="#FBBC05"
                d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"
              />
              <path
                fill="#EA4335"
                d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"
              />
            </svg>
            Sign In with Google
          </button>

          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              margin: '18px 0 6px 0',
              color: 'var(--text-muted)',
              fontSize: '11px',
              textTransform: 'uppercase',
              letterSpacing: '0.06em',
            }}
          >
            <div style={{ flex: 1, height: '1px', background: 'var(--border-subtle)' }} />
            <span style={{ padding: '0 12px' }}>or sign in with password</span>
            <div style={{ flex: 1, height: '1px', background: 'var(--border-subtle)' }} />
          </div>
        </div>

        {/* Sign In Form */}
        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
          <div>
            <label
              htmlFor="operator-email"
              className="text-xs font-semibold text-secondary"
              style={{ display: 'block', marginBottom: '6px' }}
            >
              Operator Email Address
            </label>
            <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
              <Mail
                size={16}
                color="var(--text-muted)"
                style={{ position: 'absolute', left: '12px', pointerEvents: 'none' }}
              />
              <input
                id="operator-email"
                type="email"
                autoComplete="email"
                autoFocus
                required
                className="search-input"
                style={{ width: '100%', paddingLeft: '38px' }}
                placeholder="operator@voicelock.internal"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  if (formValidation) setFormValidation(null);
                }}
              />
            </div>
          </div>

          <div>
            <label
              htmlFor="operator-password"
              className="text-xs font-semibold text-secondary"
              style={{ display: 'block', marginBottom: '6px' }}
            >
              Security Password
            </label>
            <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
              <Lock
                size={16}
                color="var(--text-muted)"
                style={{ position: 'absolute', left: '12px', pointerEvents: 'none' }}
              />
              <input
                id="operator-password"
                type={showPassword ? 'text' : 'password'}
                autoComplete="current-password"
                required
                className="search-input"
                style={{ width: '100%', paddingLeft: '38px', paddingRight: '38px' }}
                placeholder="••••••••••••"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  if (formValidation) setFormValidation(null);
                }}
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                style={{
                  position: 'absolute',
                  right: '10px',
                  background: 'transparent',
                  border: 'none',
                  color: 'var(--text-muted)',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                }}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="btn btn-primary"
            style={{ width: '100%', padding: '11px', marginTop: '6px', fontSize: '13px' }}
          >
            {loading ? 'Authenticating Principal...' : 'Sign In to Operations Console'}
          </button>
        </form>

        {/* Security Notice Footer */}
        <div
          style={{
            marginTop: '24px',
            paddingTop: '16px',
            borderTop: '1px solid var(--border-subtle)',
            textAlign: 'center',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
            <CheckCircle2 size={13} color="#10B981" />
            <span className="text-xs text-muted font-mono">
              Server-Side RS256 Token Verification
            </span>
          </div>
          <p className="text-xs text-muted" style={{ marginTop: '4px' }}>
            Authorized Personnel Only. All access sessions are cryptographically logged.
          </p>

          {/* Toggleable Firebase Setup Guide */}
          <button
            type="button"
            onClick={() => setShowSetupGuide(!showSetupGuide)}
            style={{
              marginTop: '12px',
              background: 'transparent',
              border: 'none',
              color: '#60A5FA',
              fontSize: '11px',
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
            }}
          >
            {showSetupGuide ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            Firebase Web Setup Instructions
          </button>

          {showSetupGuide && (
            <div
              style={{
                marginTop: '12px',
                textAlign: 'left',
                background: 'rgba(8, 12, 20, 0.6)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                padding: '12px',
                fontSize: '11px',
                color: 'var(--text-secondary)',
                lineHeight: '1.5',
              }}
            >
              <div className="font-semibold text-primary" style={{ marginBottom: '6px' }}>
                Firebase Setup Steps:
              </div>
              <ol style={{ paddingLeft: '16px', margin: 0 }}>
                <li>Copy <code>frontend/.env.example</code> to <code>frontend/.env.local</code>.</li>
                <li>In Firebase Console, navigate to <strong>Project Settings &gt; General &gt; Your apps &gt; Web App</strong>.</li>
                <li>Copy the Web SDK config values into <code>VITE_FIREBASE_*</code>.</li>
                <li>Under <strong>Authentication &gt; Sign-in method</strong>, enable <strong>Email/Password</strong>.</li>
                <li>Under <strong>Authorized domains</strong>, ensure <code>localhost</code> is listed.</li>
              </ol>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
