import React from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';

export const ProtectedPage: React.FC = () => {
  const { user, appToken, ssoToken } = useAuth();

  return (
    <div style={{ padding: '20px' }}>
      <h1>Protected Area</h1>
      <p>This page is only visible to authenticated users.</p>
      
      <div style={{ background: '#f8f9fa', padding: '15px', borderRadius: '8px', marginTop: '20px' }}>
        <h3>Session Details</h3>
        <p><strong>User:</strong> {JSON.stringify(user, null, 2)}</p>
        <p style={{ wordBreak: 'break-all' }}><strong>App Token:</strong> {appToken}</p>
        <p style={{ wordBreak: 'break-all' }}><strong>SSO Token (from cookie):</strong> {ssoToken || 'Missing (this is normal if using HttpOnly)'}</p>
      </div>

      <div style={{ marginTop: '20px' }}>
        <Link to="/">Back to Home</Link>
      </div>
    </div>
  );
};
