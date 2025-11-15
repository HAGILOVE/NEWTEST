import { useState, FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAppDispatch } from '@hooks/redux'
import { setCredentials } from '@store/slices/authSlice'
import api from '@services/api'
import toast from 'react-hot-toast'

export default function LoginPage() {
  const navigate = useNavigate()
  const dispatch = useAppDispatch()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setIsLoading(true)

    try {
      const data = await api.login(email, password)
      dispatch(setCredentials(data))
      localStorage.setItem('refreshToken', data.refreshToken)
      toast.success('로그인 성공!')
      navigate('/chat')
    } catch (error: any) {
      console.error('Login error:', error)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-yellow-50 to-yellow-100 dark:from-gray-900 dark:to-gray-800 px-4">
      <div className="max-w-md w-full space-y-8">
        <div className="text-center">
          <div className="flex justify-center mb-6">
            <div className="w-20 h-20 bg-kakao-yellow rounded-full flex items-center justify-center">
              <svg
                className="w-12 h-12 text-kakao-brown"
                fill="currentColor"
                viewBox="0 0 24 24"
              >
                <path d="M12 2C6.48 2 2 5.58 2 10c0 2.89 2.05 5.41 5.07 6.84-.22 1.42-.67 4.16-.76 4.69-.12.71.26.7.53.51.2-.14 3.16-2.14 4.36-2.95.6.08 1.22.13 1.85.13 5.52 0 10-3.58 10-8S17.52 2 12 2z" />
              </svg>
            </div>
          </div>
          <h2 className="text-3xl font-bold text-gray-900 dark:text-white">
            KakaoChat
          </h2>
          <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
            실시간 메신저에 로그인하세요
          </p>
        </div>

        <div className="card p-8">
          <form className="space-y-6" onSubmit={handleSubmit}>
            <div>
              <label
                htmlFor="email"
                className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2"
              >
                이메일
              </label>
              <input
                id="email"
                name="email"
                type="email"
                autoComplete="email"
                required
                className="input-field"
                placeholder="example@email.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>

            <div>
              <label
                htmlFor="password"
                className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2"
              >
                비밀번호
              </label>
              <input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                className="input-field"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>

            <div className="flex items-center justify-between">
              <div className="flex items-center">
                <input
                  id="remember-me"
                  name="remember-me"
                  type="checkbox"
                  className="h-4 w-4 text-primary-500 focus:ring-primary-500 border-gray-300 rounded"
                />
                <label
                  htmlFor="remember-me"
                  className="ml-2 block text-sm text-gray-900 dark:text-gray-300"
                >
                  로그인 상태 유지
                </label>
              </div>

              <div className="text-sm">
                <a
                  href="#"
                  className="font-medium text-primary-600 hover:text-primary-500"
                >
                  비밀번호 찾기
                </a>
              </div>
            </div>

            <div>
              <button
                type="submit"
                disabled={isLoading}
                className="w-full btn-kakao disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isLoading ? '로그인 중...' : '로그인'}
              </button>
            </div>

            <div className="text-center">
              <span className="text-sm text-gray-600 dark:text-gray-400">
                계정이 없으신가요?{' '}
              </span>
              <Link
                to="/register"
                className="text-sm font-medium text-primary-600 hover:text-primary-500"
              >
                회원가입
              </Link>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}
