import { useState } from 'react'
import { useAppSelector, useAppDispatch } from '@hooks/redux'
import { setUser } from '@store/slices/authSlice'
import { FiCamera, FiSave } from 'react-icons/fi'
import api from '@services/api'
import toast from 'react-hot-toast'

export default function ProfileSettings() {
  const dispatch = useAppDispatch()
  const { user } = useAppSelector((state) => state.auth)
  const [username, setUsername] = useState(user?.username || '')
  const [statusMessage, setStatusMessage] = useState(user?.statusMessage || '')
  const [isLoading, setIsLoading] = useState(false)

  const handleAvatarChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    // 이미지 파일 체크
    if (!file.type.startsWith('image/')) {
      toast.error('이미지 파일만 업로드 가능합니다.')
      return
    }

    // 파일 크기 체크 (5MB)
    if (file.size > 5 * 1024 * 1024) {
      toast.error('파일 크기는 5MB를 초과할 수 없습니다.')
      return
    }

    try {
      const data = await api.uploadAvatar(file)
      dispatch(setUser(data))
      toast.success('프로필 사진이 업데이트되었습니다.')
    } catch (error) {
      console.error('Failed to upload avatar:', error)
    }
  }

  const handleSaveProfile = async () => {
    if (!username.trim()) {
      toast.error('사용자 이름을 입력해주세요.')
      return
    }

    setIsLoading(true)

    try {
      const data = await api.updateProfile({
        username: username.trim(),
        statusMessage: statusMessage.trim(),
      })
      dispatch(setUser(data))
      toast.success('프로필이 업데이트되었습니다.')
    } catch (error) {
      console.error('Failed to update profile:', error)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="flex-1 flex flex-col bg-white dark:bg-gray-900 overflow-y-auto">
      {/* Header */}
      <div className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 p-4">
        <h1 className="text-xl font-bold text-gray-900 dark:text-white">
          프로필 설정
        </h1>
      </div>

      {/* Content */}
      <div className="flex-1 p-6">
        <div className="max-w-2xl mx-auto space-y-6">
          {/* Profile Picture */}
          <div className="card p-6">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
              프로필 사진
            </h2>
            <div className="flex items-center space-x-4">
              <div className="relative">
                {user?.profileImage ? (
                  <img
                    src={user.profileImage}
                    alt={user.username}
                    className="avatar-lg"
                  />
                ) : (
                  <div className="avatar-lg bg-gradient-to-br from-primary-400 to-primary-600 flex items-center justify-center text-white text-2xl font-semibold">
                    {user?.username.charAt(0).toUpperCase()}
                  </div>
                )}
                <label
                  htmlFor="avatar-upload"
                  className="absolute bottom-0 right-0 p-2 bg-kakao-yellow text-kakao-brown rounded-full cursor-pointer hover:bg-yellow-400 transition-colors"
                >
                  <FiCamera className="w-5 h-5" />
                </label>
                <input
                  id="avatar-upload"
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={handleAvatarChange}
                />
              </div>
              <div className="flex-1">
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  JPG, PNG 형식의 이미지를 업로드하세요.
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-500 mt-1">
                  최대 파일 크기: 5MB
                </p>
              </div>
            </div>
          </div>

          {/* Basic Info */}
          <div className="card p-6">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
              기본 정보
            </h2>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  이메일
                </label>
                <input
                  type="email"
                  value={user?.email || ''}
                  disabled
                  className="input-field bg-gray-100 dark:bg-gray-700 cursor-not-allowed"
                />
                <p className="text-xs text-gray-500 dark:text-gray-500 mt-1">
                  이메일은 변경할 수 없습니다.
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  사용자 이름
                </label>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="input-field"
                  placeholder="사용자 이름"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  전화번호
                </label>
                <input
                  type="tel"
                  value={user?.phone || ''}
                  disabled
                  className="input-field bg-gray-100 dark:bg-gray-700 cursor-not-allowed"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  상태 메시지
                </label>
                <textarea
                  value={statusMessage}
                  onChange={(e) => setStatusMessage(e.target.value)}
                  className="input-field resize-none"
                  rows={3}
                  placeholder="상태 메시지를 입력하세요..."
                  maxLength={100}
                />
                <p className="text-xs text-gray-500 dark:text-gray-500 mt-1 text-right">
                  {statusMessage.length}/100
                </p>
              </div>
            </div>
          </div>

          {/* Save Button */}
          <div className="flex justify-end">
            <button
              onClick={handleSaveProfile}
              disabled={isLoading}
              className="btn-kakao flex items-center space-x-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <FiSave className="w-5 h-5" />
              <span>{isLoading ? '저장 중...' : '프로필 저장'}</span>
            </button>
          </div>

          {/* Account Info */}
          <div className="card p-6">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
              계정 정보
            </h2>
            <div className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-600 dark:text-gray-400">
                  계정 생성일
                </span>
                <span className="text-gray-900 dark:text-white">
                  {user?.createdAt
                    ? new Date(user.createdAt).toLocaleDateString('ko-KR')
                    : '-'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600 dark:text-gray-400">
                  사용자 ID
                </span>
                <span className="text-gray-900 dark:text-white font-mono text-xs">
                  {user?.id}
                </span>
              </div>
            </div>
          </div>

          {/* Danger Zone */}
          <div className="card p-6 border border-red-200 dark:border-red-900">
            <h2 className="text-lg font-semibold text-red-600 dark:text-red-400 mb-4">
              위험 구역
            </h2>
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
              계정을 삭제하면 모든 데이터가 영구적으로 삭제됩니다.
            </p>
            <button className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors">
              계정 삭제
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
