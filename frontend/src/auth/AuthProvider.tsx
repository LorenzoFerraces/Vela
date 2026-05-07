import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import {
  ApiError,
  clearAccessToken,
  getAccessToken,
  getMe,
  login as apiLogin,
  onUnauthorized,
  registerUser as apiRegister,
  setAccessToken,
  type LoginRequest,
  type RegisterRequest,
  type UserPublic,
} from '../api/client'
import {
  AuthContext,
  type AuthContextValue,
  type AuthStatus,
} from './AuthContext'

interface AuthProviderProps {
  children: ReactNode
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [status, setStatus] = useState<AuthStatus>(() =>
    getAccessToken() ? 'loading' : 'anonymous'
  )
  const [user, setUser] = useState<UserPublic | null>(null)
  const cancelledRef = useRef(false)

  useEffect(() => {
    cancelledRef.current = false
    if (!getAccessToken()) {
      // Initial state already accounts for "no token"; nothing to fetch.
      return () => {
        cancelledRef.current = true
      }
    }

    void (async () => {
      try {
        const me = await getMe()
        if (cancelledRef.current) return
        setUser(me)
        setStatus('authenticated')
      } catch (error) {
        if (cancelledRef.current) return
        if (error instanceof ApiError && error.status === 401) {
          clearAccessToken()
        }
        setUser(null)
        setStatus('anonymous')
      }
    })()

    return () => {
      cancelledRef.current = true
    }
  }, [])

  useEffect(() => {
    return onUnauthorized(() => {
      setUser(null)
      setStatus('anonymous')
    })
  }, [])

  const login = useCallback(async (body: LoginRequest) => {
    const response = await apiLogin(body)
    setAccessToken(response.access_token)
    setUser(response.user)
    setStatus('authenticated')
    return response.user
  }, [])

  const register = useCallback(async (body: RegisterRequest) => {
    const response = await apiRegister(body)
    setAccessToken(response.access_token)
    setUser(response.user)
    setStatus('authenticated')
    return response.user
  }, [])

  const logout = useCallback(() => {
    clearAccessToken()
    setUser(null)
    setStatus('anonymous')
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({ status, user, login, register, logout }),
    [status, user, login, register, logout]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
