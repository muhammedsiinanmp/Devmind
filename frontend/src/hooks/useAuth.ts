import { useAuthStore } from '@/store'

export function useAuth() {
  const { isAuthenticated, logout } = useAuthStore()
  return { isAuthenticated, logout }
}
