import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAppSelector, useAppDispatch } from '@hooks/redux'
import { logout } from '@store/slices/authSlice'
import { toggleDarkMode } from '@store/slices/uiSlice'
import socketService from '@services/socket'
import { FiUsers, FiSettings, FiLogOut, FiMoon, FiSun, FiPlus } from 'react-icons/fi'
import ChatRoomList from './ChatRoomList'
import CreateRoomModal from './CreateRoomModal'

export default function Sidebar() {
  const navigate = useNavigate()
  const dispatch = useAppDispatch()
  const { user } = useAppSelector((state) => state.auth)
  const { isDarkMode } = useAppSelector((state) => state.ui)
  const [showCreateRoom, setShowCreateRoom] = useState(false)

  const handleLogout = () => {
    socketService.disconnect()
    dispatch(logout())
    navigate('/login')
  }

  return (
    <div className="h-full flex flex-col bg-white dark:bg-gray-800">
      {/* Header */}
      <div className="p-4 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-xl font-bold text-gray-900 dark:text-white">
            KakaoChat
          </h1>
          <div className="flex items-center space-x-2">
            <button
              onClick={() => dispatch(toggleDarkMode())}
              className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
              title={isDarkMode ? '라이트 모드' : '다크 모드'}
            >
              {isDarkMode ? (
                <FiSun className="w-5 h-5" />
              ) : (
                <FiMoon className="w-5 h-5" />
              )}
            </button>
            <button
              onClick={() => setShowCreateRoom(true)}
              className="p-2 rounded-lg bg-kakao-yellow text-kakao-brown hover:bg-yellow-400 transition-colors"
              title="새 채팅"
            >
              <FiPlus className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* User Info */}
        <div className="flex items-center space-x-3">
          <div className="relative">
            {user?.profileImage ? (
              <img
                src={user.profileImage}
                alt={user.username}
                className="avatar-md"
              />
            ) : (
              <div className="avatar-md bg-primary-500 flex items-center justify-center text-white font-semibold">
                {user?.username.charAt(0).toUpperCase()}
              </div>
            )}
            <span className="status-online"></span>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-gray-900 dark:text-white truncate">
              {user?.username}
            </p>
            {user?.statusMessage && (
              <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
                {user.statusMessage}
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Navigation */}
      <div className="flex border-b border-gray-200 dark:border-gray-700">
        <Link
          to="/chat"
          className="flex-1 py-3 text-center text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 border-b-2 border-primary-500"
        >
          채팅
        </Link>
        <Link
          to="/chat/friends"
          className="flex-1 py-3 text-center text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700"
        >
          친구
        </Link>
      </div>

      {/* Chat Room List */}
      <div className="flex-1 overflow-y-auto scrollbar-thin">
        <ChatRoomList />
      </div>

      {/* Footer */}
      <div className="p-3 border-t border-gray-200 dark:border-gray-700 flex space-x-2">
        <Link
          to="/chat/settings"
          className="flex-1 btn-secondary flex items-center justify-center space-x-2"
        >
          <FiSettings className="w-4 h-4" />
          <span>설정</span>
        </Link>
        <button
          onClick={handleLogout}
          className="flex-1 btn-secondary flex items-center justify-center space-x-2 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-900/20"
        >
          <FiLogOut className="w-4 h-4" />
          <span>로그아웃</span>
        </button>
      </div>

      {/* Create Room Modal */}
      {showCreateRoom && (
        <CreateRoomModal onClose={() => setShowCreateRoom(false)} />
      )}
    </div>
  )
}
