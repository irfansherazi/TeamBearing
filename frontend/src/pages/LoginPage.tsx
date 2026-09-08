import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';

export const LoginPage: React.FC = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const { login, isLoading, error, clearError } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const response = await login(email, password);
      if (response.mfaRequired) {
        navigate('/mfa', { replace: true });
      } else {
        // Always redirect to dashboard root after successful login
        navigate('/', { replace: true });
      }
    } catch (err) {
      // Error is handled by AuthProvider state
    }
  };

  return (
    <div style={{
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      height: '100vh',
      backgroundColor: 'var(--bg-primary)',
      color: 'var(--text-primary)',
      fontFamily: 'var(--font-sans)'
    }}>
      <div style={{
        width: '100%',
        maxWidth: '400px',
        padding: '2rem',
        backgroundColor: 'var(--bg-secondary)',
        borderRadius: 'var(--radius-md)',
        boxShadow: 'var(--shadow-lg)',
        border: '1px solid var(--border)'
      }}>
        <h1 style={{ textAlign: 'center', marginBottom: '2rem', fontSize: '1.5rem', fontWeight: 700 }}>vReview Login</h1>
        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
          <div className="form-group">
            <label>Email</label>
            <input 
              type="email" 
              className="form-input"
              placeholder="Enter your email"
              value={email} 
              onChange={(e) => { setEmail(e.target.value); clearError(); }} 
              required 
              style={{ width: '100%', boxSizing: 'border-box' }}
            />
          </div>
          <div className="form-group">
            <label>Password</label>
            <input 
              type="password" 
              className="form-input"
              placeholder="Enter your password"
              value={password} 
              onChange={(e) => { setPassword(e.target.value); clearError(); }} 
              required 
              style={{ width: '100%', boxSizing: 'border-box' }}
            />
          </div>
          {error && (
            <div style={{ color: 'var(--status-failed)', fontSize: '0.875rem', textAlign: 'center' }}>
              {error}
            </div>
          )}
          <button 
            type="submit" 
            className={`execute-btn ${isLoading ? 'loading' : ''}`}
            disabled={isLoading}
            style={{
              padding: '0.75rem',
              fontWeight: 'bold',
              marginTop: '0.5rem',
              width: '100%',
              display: 'flex',
              justifyContent: 'center',
              alignItems: 'center'
            }}
          >
            {isLoading ? 'Logging in...' : 'Sign In'}
          </button>
        </form>
      </div>
    </div>
  );
};
