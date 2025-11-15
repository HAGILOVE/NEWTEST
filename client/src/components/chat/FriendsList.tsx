import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FiSearch, FiUserPlus, FiStar, FiMoreVertical } from 'react-icons/fi'
import api from '@services/api'
import toast from 'react-hot-toast'
import { Friend } from '@types/index'

export default function FriendsList() {
  const navigate = useNavigate()
  const [friends, setFriends] = useState<Friend[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [showAddFriend, setShowAddFriend] = useState(false)

  useEffect(() => {
    loadFriends()
  }, [])

  const loadFriends = async () => {
    try {
      const data = await api.getFriends()
      setFriends(data)
    } catch (error) {
      console.error('Failed to load friends:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const handleToggleFavorite = async (friendshipId: string) => {
    try {
      await api.toggleFavorite(friendshipId)
      setFriends((prev) =>
        prev.map((friend) =>
          friend.friendshipId === friendshipId
            ? { ...friend, isFavorite: !friend.isFavorite }
            : friend
        )
      )
      toast.success('즐겨찾기가 업데이트되었습니다.')
    } catch (error) {
      console.error('Failed to toggle favorite:', error)
    }
  }

  const handleRemoveFriend = async (friendshipId: string) => {
    if (!confirm('정말 친구를 삭제하시겠습니까?')) return

    try {
      await api.removeFriend(friendshipId)
      setFriends((prev) =>
        prev.filter((friend) => friend.friendshipId !== friendshipId)
      )
      toast.success('친구가 삭제되었습니다.')
    } catch (error) {
      console.error('Failed to remove friend:', error)
    }
  }

  const handleStartChat = async (friendId: string) => {
    try {
      const room = await api.createRoom({
        type: 'direct',
        memberIds: [friendId],
      })
      navigate(`/chat/room/${room.id}`)
    } catch (error) {
      console.error('Failed to start chat:', error)
    }
  }

  const filteredFriends = friends.filter((friend) =>
    friend.username.toLowerCase().includes(searchQuery.toLowerCase())
  )

  const favoriteFriends = filteredFriends.filter((friend) => friend.isFavorite)
  const regularFriends = filteredFriends.filter((friend) => !friend.isFavorite)

  return (
    <div className="flex-1 flex flex-col bg-white dark:bg-gray-900">
      {/* Header */}
      <div className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 p-4">
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-xl font-bold text-gray-900 dark:text-white">
            친구
          </h1>
          <button
            onClick={() => setShowAddFriend(!showAddFriend)}
            className="p-2 rounded-lg bg-kakao-yellow text-kakao-brown hover:bg-yellow-400 transition-colors"
            title="친구 추가"
          >
            <FiUserPlus className="w-5 h-5" />
          </button>
        </div>

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

        <div className="mt-3 text-sm text-gray-600 dark:text-gray-400">
          친구 {friends.length}명
        </div>
      </div>

      {/* Friends List */}
      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {isLoading ? (
          <div className="flex items-center justify-center h-full">
            <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-primary-500"></div>
          </div>
        ) : filteredFriends.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full p-8 text-center">
            <div className="w-16 h-16 bg-gray-200 dark:bg-gray-700 rounded-full flex items-center justify-center mb-4">
              <FiUserPlus className="w-8 h-8 text-gray-400" />
            </div>
            <p className="text-gray-500 dark:text-gray-400">
              {searchQuery ? '검색 결과가 없습니다' : '아직 친구가 없습니다'}
            </p>
            {!searchQuery && (
              <button
                onClick={() => setShowAddFriend(true)}
                className="mt-4 btn-kakao"
              >
                친구 추가하기
              </button>
            )}
          </div>
        ) : (
          <div>
            {/* Favorites */}
            {favoriteFriends.length > 0 && (
              <div className="mb-4">
                <div className="px-4 py-2 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                  <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 flex items-center">
                    <FiStar className="w-4 h-4 mr-2 text-yellow-500" />
                    즐겨찾기 ({favoriteFriends.length})
                  </h3>
                </div>
                {favoriteFriends.map((friend) => (
                  <FriendItem
                    key={friend.id}
                    friend={friend}
                    onToggleFavorite={handleToggleFavorite}
                    onRemove={handleRemoveFriend}
                    onStartChat={handleStartChat}
                  />
                ))}
              </div>
            )}

            {/* Regular Friends */}
            {regularFriends.length > 0 && (
              <div>
                {favoriteFriends.length > 0 && (
                  <div className="px-4 py-2 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                    <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
                      친구 ({regularFriends.length})
                    </h3>
                  </div>
                )}
                {regularFriends.map((friend) => (
                  <FriendItem
                    key={friend.id}
                    friend={friend}
                    onToggleFavorite={handleToggleFavorite}
                    onRemove={handleRemoveFriend}
                    onStartChat={handleStartChat}
                  />
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

interface FriendItemProps {
  friend: Friend
  onToggleFavorite: (friendshipId: string) => void
  onRemove: (friendshipId: string) => void
  onStartChat: (friendId: string) => void
}

function FriendItem({
  friend,
  onToggleFavorite,
  onRemove,
  onStartChat,
}: FriendItemProps) {
  const [showMenu, setShowMenu] = useState(false)

  return (
    <div className="relative flex items-center p-4 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
      <div
        className="flex items-center flex-1 cursor-pointer"
        onClick={() => onStartChat(friend.id)}
      >
        <div className="relative flex-shrink-0">
          {friend.profileImage ? (
            <img
              src={friend.profileImage}
              alt={friend.username}
              className="avatar-md"
            />
          ) : (
            <div className="avatar-md bg-gradient-to-br from-primary-400 to-primary-600 flex items-center justify-center text-white font-semibold">
              {friend.username.charAt(0).toUpperCase()}
            </div>
          )}
          {friend.isOnline && <span className="status-online"></span>}
        </div>

        <div className="ml-3 flex-1 min-w-0">
          <div className="flex items-center">
            <p className="text-sm font-semibold text-gray-900 dark:text-white truncate">
              {friend.username}
            </p>
            {friend.isFavorite && (
              <FiStar className="w-4 h-4 ml-2 text-yellow-500 fill-current" />
            )}
          </div>
          {friend.statusMessage && (
            <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
              {friend.statusMessage}
            </p>
          )}
        </div>
      </div>

      <div className="relative">
        <button
          onClick={() => setShowMenu(!showMenu)}
          className="p-2 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700"
        >
          <FiMoreVertical className="w-5 h-5" />
        </button>

        {showMenu && (
          <>
            <div
              className="fixed inset-0 z-10"
              onClick={() => setShowMenu(false)}
            />
            <div className="absolute right-0 mt-2 w-48 bg-white dark:bg-gray-700 rounded-lg shadow-lg z-20 py-1">
              <button
                onClick={() => {
                  onToggleFavorite(friend.friendshipId)
                  setShowMenu(false)
                }}
                className="w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-600"
              >
                {friend.isFavorite ? '즐겨찾기 해제' : '즐겨찾기 추가'}
              </button>
              <button
                onClick={() => {
                  onRemove(friend.friendshipId)
                  setShowMenu(false)
                }}
                className="w-full px-4 py-2 text-left text-sm text-red-600 hover:bg-gray-100 dark:hover:bg-gray-600"
              >
                친구 삭제
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
