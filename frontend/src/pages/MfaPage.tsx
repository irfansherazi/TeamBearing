import React, { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';

export const MfaPage: React.FC = () => {
  const [code, setCode] = useState('');
  const { verifyMfa, isLoading, error, clearError, mfaToken } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const from = (location.state as any)?.from?.pathname || '/';

  if (!mfaToken && !isLoading) {
    return <p>Invalid session. Please login again.</p>;
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await verifyMfa(code);
      navigate(from, { replace: true });
    } catch (err) {
      // Handled by AuthProvider
    }
  };

  return (
    <div style={{ maxWidth: '400px', margin: '100px auto', padding: '20px', border: '1px solid #ccc', borderRadius: '8px' }}>
      <h1>Verification Code</h1>
      <p>Please enter the 6-digit code sent to your device.</p>
      <form onSubmit={handleSubmit}>
        <div style={{ marginBottom: '15px' }}>
          <input 
            type="text" 
            value={code} 
            onChange={(e) => { setCode(e.target.value); clearError(); }} 
            required 
            placeholder="123456"
            maxLength={6}
            style={{ width: '100%', padding: '12px', fontSize: '1.2em', textAlign: 'center', letterSpacing: '5px' }}
          />
        </div>
        {error && <div style={{ color: 'red', marginBottom: '15px' }}>{error}</div>}
        <button 
          type="submit" 
          disabled={isLoading}
          style={{ width: '100%', padding: '10px', background: '#28a745', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer' }}
        >
          {isLoading ? 'Verifying...' : 'Verify'}
        </button>
      </form>
      <div style={{ marginTop: '20px', fontSize: '0.9em', color: '#666' }}>
        <p>Tip: Use code "123456" for success.</p>
      </div>
    </div>
  );
};
