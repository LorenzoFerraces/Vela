import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Navbar from './components/Navbar'
import RequireAuth from './auth/RequireAuth'
import RequireStaff, { RequireAdmin } from './auth/RequireRole'
import Home from './pages/Home'
import LoginPage from './pages/LoginPage'

const DashboardPage = lazy(() => import('./pages/DashboardPage'))
const ContainersPage = lazy(() => import('./pages/ContainersPage'))
const BuilderPage = lazy(() => import('./pages/BuilderPage'))
const ImagesPage = lazy(() => import('./pages/ImagesPage'))
const TeamsPage = lazy(() => import('./pages/TeamsPage'))
const AdminPage = lazy(() => import('./pages/AdminPage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))
const LogsPage = lazy(() => import('./pages/LogsPage'))
const AuditLogPage = lazy(() => import('./pages/AuditLogPage'))
const StacksPage = lazy(() => import('./pages/StacksPage'))
const StackBuilderPage = lazy(() => import('./pages/stacks/StackBuilderPage'))
const ResourceDashboardPage = lazy(() => import('./pages/ResourceDashboardPage'))
export default function App() {
  return (
    <Suspense
      fallback={
        <div className="app-shell">
          <Navbar />
          <main className="main-content" role="status" aria-live="polite">
            <span className="skeleton skeleton--detail-title" />
            <span className="skeleton skeleton--team-row" />
            <span className="skeleton skeleton--team-row" />
          </main>
        </div>
      }
    >
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<Layout />}>
          <Route path="/" element={<Home />} />
          <Route
            path="/dashboard"
            element={
              <RequireAuth>
                <DashboardPage />
              </RequireAuth>
            }
          />
          <Route
            path="/containers/:containerId/resources"
            element={
              <RequireAuth>
                <ResourceDashboardPage />
              </RequireAuth>
            }
          />
          <Route
            path="/containers"
            element={
              <RequireAuth>
                <ContainersPage />
              </RequireAuth>
            }
          />
          <Route
            path="/builder"
            element={
              <RequireAuth>
                <BuilderPage />
              </RequireAuth>
            }
          />
          <Route
            path="/images"
            element={
              <RequireAuth>
                <ImagesPage />
              </RequireAuth>
            }
          />
          <Route
            path="/teams/:projectId?"
            element={
              <RequireAuth>
                <RequireStaff>
                  <TeamsPage />
                </RequireStaff>
              </RequireAuth>
            }
          />
          <Route
            path="/admin"
            element={
              <RequireAuth>
                <RequireAdmin>
                  <AdminPage />
                </RequireAdmin>
              </RequireAuth>
            }
          />
          <Route
            path="/settings"
            element={
              <RequireAuth>
                <SettingsPage />
              </RequireAuth>
            }
          />
          <Route
            path="/logs"
            element={
              <RequireAuth>
                <LogsPage />
              </RequireAuth>
            }
          />
          <Route
            path="/audit"
            element={
              <RequireAuth>
                <AuditLogPage />
              </RequireAuth>
            }
          />
          <Route
            path="/stacks"
            element={
              <RequireAuth>
                <StacksPage />
              </RequireAuth>
            }
          />
          <Route
            path="/stacks/new"
            element={
              <RequireAuth>
                <StackBuilderPage />
              </RequireAuth>
            }
          />
          <Route
            path="/stacks/:id"
            element={
              <RequireAuth>
                <StackBuilderPage />
              </RequireAuth>
            }
          />
        </Route>
      </Routes>
    </Suspense>
  )
}
