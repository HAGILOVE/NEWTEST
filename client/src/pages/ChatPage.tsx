import { useEffect } from 'react'
import { Routes, Route } from 'react-router-dom'
import { useAppDispatch, useAppSelector } from '@hooks/redux'
import { setRooms } from '@store/slices/chatSlice'
import { addMessage, markMessageAsRead } from '@store/slices/chatSlice'
import { setTyping } from '@store/slices/uiSlice'
import api from '@services/api'
import socketService from '@services/socket'
import Sidebar from '@components/chat/Sidebar'
import ChatWindow from '@components/chat/ChatWindow'
import FriendsList from '@components/chat/FriendsList'
import ProfileSettings from '@components/chat/ProfileSettings'
import { Message, TypingEvent, MessageReadEvent } from '@types/index'

export default function ChatPage() {
  const dispatch = useAppDispatch()
  const { isSidebarOpen } = useAppSelector((state) => state.ui)
  const { user } = useAppSelector((state) => state.auth)

  useEffect(() => {
    // 채팅방 목록 로드
    const loadRooms = async () => {
      try {
        const rooms = await api.getRooms()
        dispatch(setRooms(rooms))
      } catch (error) {
        console.error('Failed to load rooms:', error)
      }
    }

    loadRooms()
  }, [dispatch])

  useEffect(() => {
    // WebSocket 이벤트 리스너
    const handleNewMessage = (message: Message) => {
      dispatch(addMessage(message))

      // 자동 읽음 처리 (활성 방인 경우)
      if (message.senderId !== user?.id) {
        socketService.markAsRead(message.roomId, [message.id])
      }
    }

    const handleTyping = (data: TypingEvent) => {
      dispatch(
        setTyping({
          roomId: data.roomId,
          userId: data.userId,
          isTyping: data.isTyping,
        })
      )
    }

    const handleMessageRead = (data: MessageReadEvent) => {
      dispatch(
        markMessageAsRead({
          roomId: data.roomId,
          messageId: data.messageId,
          userId: data.userId,
        })
      )
    }

    socketService.on('new_message', handleNewMessage)
    socketService.on('user_typing', handleTyping)
    socketService.on('message_read', handleMessageRead)

    return () => {
      socketService.off('new_message', handleNewMessage)
      socketService.off('user_typing', handleTyping)
      socketService.off('message_read', handleMessageRead)
    }
  }, [dispatch, user])

  return (
    <div className="flex h-screen bg-gray-100 dark:bg-gray-900">
      {/* Sidebar */}
      <div
        className={`${
          isSidebarOpen ? 'w-80' : 'w-0'
        } transition-all duration-300 overflow-hidden border-r border-gray-200 dark:border-gray-700`}
      >
        <Sidebar />
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <Routes>
          <Route path="/" element={<ChatWindow />} />
          <Route path="/room/:roomId" element={<ChatWindow />} />
          <Route path="/friends" element={<FriendsList />} />
          <Route path="/settings" element={<ProfileSettings />} />
        </Routes>
      </div>
    </div>
  )
}
