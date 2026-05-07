import { createContext, useContext } from 'react'
import type { LoginRequest, RegisterRequest, UserPublic } from '../api/client'

export type AuthStatus = 'loading' | 'authenticated' | 'anonymous'

export interface AuthContextValue {
  status: AuthStatus
  user: UserPublic | null
  login: (body: LoginRequest) => Promise<UserPublic>
  register: (body: RegisterRequest) => Promise<UserPublic>
  logout: () => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error('useAuth must be used inside an <AuthProvider>')
  }
  return ctx
}
