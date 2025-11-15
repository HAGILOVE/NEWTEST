import { useState, FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAppDispatch } from '@hooks/redux'
import { setCredentials } from '@store/slices/authSlice'
import api from '@services/api'
import toast from 'react-hot-toast'

export default function RegisterPage() {
  const navigate = useNavigate()
  const dispatch = useAppDispatch()
  const [formData, setFormData] = useState({
    email: '',
    username: '',
    password: '',
    confirmPassword: '',
    phone: '',
  })
  const [isLoading, setIsLoading] = useState(false)

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFormData({
      ...formData,
      [e.target.name]: e.target.value,
    })
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()

    if (formData.password !== formData.confirmPassword) {
      toast.error('비밀번호가 일치하지 않습니다.')
      return
    }

    if (formData.password.length < 6) {
      toast.error('비밀번호는 최소 6자 이상이어야 합니다.')
      return
    }

    setIsLoading(true)

    try {
      const { confirmPassword, ...registerData } = formData
      const data = await api.register(registerData)
      dispatch(setCredentials(data))
      localStorage.setItem('refreshToken', data.refreshToken)
      toast.success('회원가입 성공!')
      navigate('/chat')
    } catch (error: any) {
      console.error('Register error:', error)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-yellow-50 to-yellow-100 dark:from-gray-900 dark:to-gray-800 px-4 py-12">
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
            새로운 계정을 만드세요
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
                value={formData.email}
                onChange={handleChange}
              />
            </div>

            <div>
              <label
                htmlFor="username"
                className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2"
              >
                사용자 이름
              </label>
              <input
                id="username"
                name="username"
                type="text"
                autoComplete="username"
                required
                className="input-field"
                placeholder="홍길동"
                value={formData.username}
                onChange={handleChange}
              />
            </div>

            <div>
              <label
                htmlFor="phone"
                className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2"
              >
                전화번호 (선택)
              </label>
              <input
                id="phone"
                name="phone"
                type="tel"
                autoComplete="tel"
                className="input-field"
                placeholder="010-1234-5678"
                value={formData.phone}
                onChange={handleChange}
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
                autoComplete="new-password"
                required
                className="input-field"
                placeholder="••••••••"
                value={formData.password}
                onChange={handleChange}
              />
            </div>

            <div>
              <label
                htmlFor="confirmPassword"
                className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2"
              >
                비밀번호 확인
              </label>
              <input
                id="confirmPassword"
                name="confirmPassword"
                type="password"
                autoComplete="new-password"
                required
                className="input-field"
                placeholder="••••••••"
                value={formData.confirmPassword}
                onChange={handleChange}
              />
            </div>

            <div>
              <button
                type="submit"
                disabled={isLoading}
                className="w-full btn-kakao disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isLoading ? '가입 중...' : '회원가입'}
              </button>
            </div>

            <div className="text-center">
              <span className="text-sm text-gray-600 dark:text-gray-400">
                이미 계정이 있으신가요?{' '}
              </span>
              <Link
                to="/login"
                className="text-sm font-medium text-primary-600 hover:text-primary-500"
              >
                로그인
              </Link>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}
