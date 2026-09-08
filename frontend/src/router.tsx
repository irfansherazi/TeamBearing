import { createBrowserRouter, Navigate } from 'react-router-dom';
import { LoginPage } from './pages/LoginPage';
import { MfaPage } from './pages/MfaPage';
import { AiReviewPage } from './pages/AiReviewPage';
import { AiReviewHistoryPage } from './pages/AiReviewHistoryPage';
import { MemoryWatchPage } from './pages/MemoryWatchPage';
import { MemoryWatchHistoryPage } from './pages/MemoryWatchHistoryPage';
import { ProtectedRoute } from './auth/ProtectedRoute';
import { AppShell } from './components/AppShell';

export const router = createBrowserRouter([
  {
    path: '/',
    element: (
      <ProtectedRoute>
        <AppShell>
          <AiReviewPage />
        </AppShell>
      </ProtectedRoute>
    ),
  },
  {
    path: '/history',
    element: (
      <ProtectedRoute>
        <AppShell>
          <AiReviewHistoryPage />
        </AppShell>
      </ProtectedRoute>
    ),
  },
  {
    path: '/memory',
    element: (
      <ProtectedRoute>
        <AppShell>
          <MemoryWatchPage />
        </AppShell>
      </ProtectedRoute>
    ),
  },
  {
    path: '/memory/history',
    element: (
      <ProtectedRoute>
        <AppShell>
          <MemoryWatchHistoryPage />
        </AppShell>
      </ProtectedRoute>
    ),
  },
  {
    path: '/ai-review',
    element: <Navigate to="/" replace />,
  },
  {
    path: '/login',
    element: <LoginPage />,
  },
  {
    path: '/mfa',
    element: <MfaPage />,
  },
]);

