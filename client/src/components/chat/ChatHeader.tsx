import { FiMoreVertical, FiMenu } from 'react-icons/fi'
import { useAppDispatch, useAppSelector } from '@hooks/redux'
import { toggleSidebar } from '@store/slices/uiSlice'
import { ChatRoom } from '@types/index'

interface ChatHeaderProps {
  room: ChatRoom | null
}

export default function ChatHeader({ room }: ChatHeaderProps) {
  const dispatch = useAppDispatch()
  const { user } = useAppSelector((state) => state.auth)

  if (!room) return null

  const getRoomName = () => {
    if (room.type === 'group') {
      return room.name || '그룹 채팅'
    }
    const otherMember = room.members?.find((m) => m.id !== user?.id)
    return otherMember?.username || '알 수 없는 사용자'
  }

  const getMembersInfo = () => {
    if (room.type === 'group') {
      return `${room.members?.length || 0}명`
    }
    const otherMember = room.members?.find((m) => m.id !== user?.id)
    return otherMember?.isOnline ? '온라인' : '오프라인'
  }

  return (
    <div className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-4 py-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <button
            onClick={() => dispatch(toggleSidebar())}
            className="lg:hidden p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700"
          >
            <FiMenu className="w-5 h-5" />
          </button>

          <div className="relative">
            {room.profileImage ? (
              <img
                src={room.profileImage}
                alt={getRoomName()}
                className="avatar-md"
              />
            ) : (
              <div className="avatar-md bg-gradient-to-br from-primary-400 to-primary-600 flex items-center justify-center text-white font-semibold">
                {getRoomName().charAt(0).toUpperCase()}
              </div>
            )}
          </div>

          <div>
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
              {getRoomName()}
            </h2>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {getMembersInfo()}
            </p>
          </div>
        </div>

        <button className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700">
          <FiMoreVertical className="w-5 h-5" />
        </button>
      </div>
    </div>
  )
}
