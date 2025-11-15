import { useNavigate } from 'react-router-dom'
import { useAppSelector } from '@hooks/redux'
import { formatDistanceToNow } from 'date-fns'
import { ko } from 'date-fns/locale'

export default function ChatRoomList() {
  const navigate = useNavigate()
  const { rooms } = useAppSelector((state) => state.chat)
  const { activeRoomId } = useAppSelector((state) => state.ui)

  const getRoomName = (room: any) => {
    if (room.type === 'group') {
      return room.name || '그룹 채팅'
    }
    // 1:1 채팅의 경우 상대방 이름 표시
    const otherMember = room.members?.[0]
    return otherMember?.username || '알 수 없는 사용자'
  }

  const getRoomImage = (room: any) => {
    if (room.profileImage) {
      return room.profileImage
    }
    if (room.type === 'direct' && room.members?.[0]) {
      return room.members[0].profileImage
    }
    return null
  }

  const formatTime = (date: Date) => {
    try {
      return formatDistanceToNow(new Date(date), {
        addSuffix: true,
        locale: ko,
      })
    } catch {
      return ''
    }
  }

  if (rooms.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-8 text-center">
        <div className="w-16 h-16 bg-gray-200 dark:bg-gray-700 rounded-full flex items-center justify-center mb-4">
          <svg
            className="w-8 h-8 text-gray-400"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
            />
          </svg>
        </div>
        <p className="text-gray-500 dark:text-gray-400">
          아직 채팅방이 없습니다
        </p>
        <p className="text-sm text-gray-400 dark:text-gray-500 mt-2">
          새 채팅을 시작해보세요!
        </p>
      </div>
    )
  }

  return (
    <div>
      {rooms.map((room) => (
        <div
          key={room.id}
          onClick={() => navigate(`/chat/room/${room.id}`)}
          className={`chat-room-item ${
            activeRoomId === room.id ? 'active' : ''
          }`}
        >
          <div className="relative flex-shrink-0">
            {getRoomImage(room) ? (
              <img
                src={getRoomImage(room)!}
                alt={getRoomName(room)}
                className="avatar-md"
              />
            ) : (
              <div className="avatar-md bg-gradient-to-br from-primary-400 to-primary-600 flex items-center justify-center text-white font-semibold">
                {getRoomName(room).charAt(0).toUpperCase()}
              </div>
            )}
            {room.type === 'direct' && room.members?.[0]?.isOnline && (
              <span className="status-online"></span>
            )}
          </div>

          <div className="flex-1 min-w-0 ml-3">
            <div className="flex items-center justify-between mb-1">
              <p className="text-sm font-semibold text-gray-900 dark:text-white truncate">
                {getRoomName(room)}
              </p>
              {room.lastMessage && (
                <span className="text-xs text-gray-500 dark:text-gray-400 ml-2 flex-shrink-0">
                  {formatTime(room.lastMessage.createdAt)}
                </span>
              )}
            </div>

            <div className="flex items-center justify-between">
              <p className="text-sm text-gray-600 dark:text-gray-400 truncate">
                {room.lastMessage
                  ? room.lastMessage.type === 'text'
                    ? room.lastMessage.content
                    : room.lastMessage.type === 'image'
                    ? '📷 사진'
                    : '📎 파일'
                  : '메시지가 없습니다'}
              </p>
              {room.unreadCount > 0 && (
                <span className="badge ml-2">{room.unreadCount}</span>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
