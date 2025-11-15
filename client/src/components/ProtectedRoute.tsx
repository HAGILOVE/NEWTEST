import { useEffect } from 'react'
import { Navigate } from 'react-router-dom'
import { useAppDispatch, useAppSelector } from '@hooks/redux'
import { setUser, setLoading, logout } from '@store/slices/authSlice'
import api from '@services/api'
import socketService from '@services/socket'

interface ProtectedRouteProps {
  children: React.ReactNode
}

export default function ProtectedRoute({ children }: ProtectedRouteProps) {
  const dispatch = useAppDispatch()
  const { isAuthenticated, isLoading, accessToken } = useAppSelector(
    (state) => state.auth
  )

  useEffect(() => {
    const fetchUser = async () => {
      if (!accessToken) {
        dispatch(setLoading(false))
        return
      }

      try {
        const user = await api.getCurrentUser()
        dispatch(setUser(user))

        // WebSocket 연결
        socketService.connect(accessToken)
      } catch (error) {
        console.error('Failed to fetch user:', error)
        dispatch(logout())
      }
    }

    if (isAuthenticated && !isLoading) {
      fetchUser()
    } else if (!isAuthenticated) {
      dispatch(setLoading(false))
    }
  }, [dispatch, accessToken, isAuthenticated, isLoading])

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900">
        <div className="text-center">
          <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-primary-500"></div>
          <p className="mt-4 text-gray-600 dark:text-gray-400">로딩 중...</p>
        </div>
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  return <>{children}</>
}
