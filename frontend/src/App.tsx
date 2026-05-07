import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import RequireAuth from './auth/RequireAuth'
import Home from './pages/Home'
import ContainersPage from './pages/ContainersPage'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import PlaceholderPage from './pages/PlaceholderPage'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route element={<Layout />}>
        <Route path="/" element={<Home />} />
        <Route
          path="/dashboard"
          element={
            <RequireAuth>
              <PlaceholderPage title="Dashboard" />
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
              <PlaceholderPage title="Builder" />
            </RequireAuth>
          }
        />
        <Route
          path="/images"
          element={
            <RequireAuth>
              <PlaceholderPage title="Images" />
            </RequireAuth>
          }
        />
        <Route
          path="/settings"
          element={
            <RequireAuth>
              <PlaceholderPage title="Settings" />
            </RequireAuth>
          }
        />
      </Route>
    </Routes>
  )
}
