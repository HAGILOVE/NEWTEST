import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useEffect } from 'react'
import { useAppDispatch, useAppSelector } from './hooks/redux'
import { setDarkMode } from './store/slices/uiSlice'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import ChatPage from './pages/ChatPage'
import ProtectedRoute from './components/ProtectedRoute'

function App() {
  const dispatch = useAppDispatch()
  const { isDarkMode } = useAppSelector((state) => state.ui)

  useEffect(() => {
    // 다크모드 설정 로드
    const savedDarkMode = localStorage.getItem('darkMode') === 'true'
    dispatch(setDarkMode(savedDarkMode))
  }, [dispatch])

  useEffect(() => {
    // 다크모드 클래스 적용
    if (isDarkMode) {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }
  }, [isDarkMode])

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route
          path="/chat/*"
          element={
            <ProtectedRoute>
              <ChatPage />
            </ProtectedRoute>
          }
        />
        <Route path="/" element={<Navigate to="/chat" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
