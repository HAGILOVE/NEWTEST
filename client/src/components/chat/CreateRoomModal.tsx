import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAppSelector } from '@hooks/redux'
import { FiX, FiSearch } from 'react-icons/fi'
import api from '@services/api'
import toast from 'react-hot-toast'
import { Friend } from '@types/index'

interface CreateRoomModalProps {
  onClose: () => void
}

export default function CreateRoomModal({ onClose }: CreateRoomModalProps) {
  const navigate = useNavigate()
  const { user } = useAppSelector((state) => state.auth)
  const [friends, setFriends] = useState<Friend[]>([])
  const [selectedFriends, setSelectedFriends] = useState<string[]>([])
  const [roomName, setRoomName] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    loadFriends()
  }, [])

  const loadFriends = async () => {
    try {
      const data = await api.getFriends()
      setFriends(data)
    } catch (error) {
      console.error('Failed to load friends:', error)
    }
  }

  const handleToggleFriend = (friendId: string) => {
    setSelectedFriends((prev) =>
      prev.includes(friendId)
        ? prev.filter((id) => id !== friendId)
        : [...prev, friendId]
    )
  }

  const handleCreateRoom = async () => {
    if (selectedFriends.length === 0) {
      toast.error('최소 1명의 친구를 선택해주세요.')
      return
    }

    setIsLoading(true)

    try {
      const roomData = await api.createRoom({
        type: selectedFriends.length === 1 ? 'direct' : 'group',
        memberIds: selectedFriends,
        name: selectedFriends.length > 1 ? roomName : undefined,
      })

      toast.success('채팅방이 생성되었습니다.')
      navigate(`/chat/room/${roomData.id}`)
      onClose()
    } catch (error) {
      console.error('Failed to create room:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const filteredFriends = friends.filter((friend) =>
    friend.username.toLowerCase().includes(searchQuery.toLowerCase())
  )

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white dark:bg-gray-800 rounded-lg w-full max-w-md max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            새 채팅
          </h2>
          <button
            onClick={onClose}
            className="p-1 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700"
          >
            <FiX className="w-5 h-5" />
          </button>
        </div>

        {/* Search */}
        <div className="p-4 border-b border-gray-200 dark:border-gray-700">
          <div className="relative">
            <FiSearch className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              placeholder="친구 검색..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-10 pr-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 dark:bg-gray-700 dark:text-white"
            />
          </div>
        </div>

        {/* Group Name (if multiple selected) */}
        {selectedFriends.length > 1 && (
          <div className="p-4 border-b border-gray-200 dark:border-gray-700">
            <input
              type="text"
              placeholder="그룹 채팅방 이름 (선택)"
              value={roomName}
              onChange={(e) => setRoomName(e.target.value)}
              className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 dark:bg-gray-700 dark:text-white"
            />
          </div>
        )}

        {/* Friends List */}
        <div className="flex-1 overflow-y-auto p-4 space-y-2 scrollbar-thin">
          {filteredFriends.length === 0 ? (
            <div className="text-center py-8 text-gray-500 dark:text-gray-400">
              {searchQuery ? '검색 결과가 없습니다' : '친구가 없습니다'}
            </div>
          ) : (
            filteredFriends.map((friend) => (
              <div
                key={friend.id}
                onClick={() => handleToggleFriend(friend.id)}
                className={`flex items-center p-3 rounded-lg cursor-pointer transition-colors ${
                  selectedFriends.includes(friend.id)
                    ? 'bg-primary-100 dark:bg-primary-900/20'
                    : 'hover:bg-gray-100 dark:hover:bg-gray-700'
                }`}
              >
                <input
                  type="checkbox"
                  checked={selectedFriends.includes(friend.id)}
                  onChange={() => {}}
                  className="mr-3 w-5 h-5 text-primary-500 rounded focus:ring-primary-500"
                />

                <div className="relative flex-shrink-0">
                  {friend.profileImage ? (
                    <img
                      src={friend.profileImage}
                      alt={friend.username}
                      className="avatar-md"
                    />
                  ) : (
                    <div className="avatar-md bg-gray-400 flex items-center justify-center text-white font-semibold">
                      {friend.username.charAt(0).toUpperCase()}
                    </div>
                  )}
                  {friend.isOnline && <span className="status-online"></span>}
                </div>

                <div className="ml-3 flex-1 min-w-0">
                  <p className="text-sm font-semibold text-gray-900 dark:text-white truncate">
                    {friend.username}
                  </p>
                  {friend.statusMessage && (
                    <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
                      {friend.statusMessage}
                    </p>
                  )}
                </div>
              </div>
            ))
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-gray-200 dark:border-gray-700 flex space-x-2">
          <button
            onClick={onClose}
            className="flex-1 btn-secondary"
            disabled={isLoading}
          >
            취소
          </button>
          <button
            onClick={handleCreateRoom}
            disabled={selectedFriends.length === 0 || isLoading}
            className="flex-1 btn-kakao disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isLoading
              ? '생성 중...'
              : `${
                  selectedFriends.length === 1 ? '채팅 시작' : '그룹 만들기'
                } ${selectedFriends.length > 0 ? `(${selectedFriends.length})` : ''}`}
          </button>
        </div>
      </div>
    </div>
  )
}
