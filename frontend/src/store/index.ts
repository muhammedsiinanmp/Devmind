import { create } from 'zustand'

interface AuthState {
  accessToken: string | null
  isAuthenticated: boolean
  setTokens: (access: string) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: localStorage.getItem('access_token'),
  isAuthenticated: !!localStorage.getItem('access_token'),
  setTokens: (access) => {
    localStorage.setItem('access_token', access)
    set({ accessToken: access, isAuthenticated: true })
  },
  logout: () => {
    localStorage.removeItem('access_token')
    set({ accessToken: null, isAuthenticated: false })
  },
}))
