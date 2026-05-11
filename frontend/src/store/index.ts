import { create } from 'zustand'

interface AuthState {
  accessToken: string | null
  refreshToken: string | null
  isAuthenticated: boolean
  setTokens: (access: string, refresh?: string) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: localStorage.getItem('access_token'),
  refreshToken: localStorage.getItem('refresh_token'),
  isAuthenticated: !!localStorage.getItem('access_token'),

  setTokens: (access, refresh) => {
    localStorage.setItem('access_token', access)
    if (refresh) {
      localStorage.setItem('refresh_token', refresh)
      set({ accessToken: access, refreshToken: refresh, isAuthenticated: true })
    } else {
      set({ accessToken: access, isAuthenticated: true })
    }
  },

  logout: () => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    set({ accessToken: null, refreshToken: null, isAuthenticated: false })
  },
}))
