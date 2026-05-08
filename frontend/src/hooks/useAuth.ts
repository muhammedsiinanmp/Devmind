import { useAuthStore } from '../store/index'

export function useAuth() {
  const { isAuthenticated, logout } = useAuthStore()
  return { isAuthenticated, logout }
}
