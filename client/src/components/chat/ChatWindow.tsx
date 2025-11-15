import { useEffect, useState, useRef } from 'react'
import { useParams } from 'react-router-dom'
import { useAppSelector, useAppDispatch } from '@hooks/redux'
import { setActiveRoom, setMessages, addMessage } from '@store/slices/chatSlice'
import { setActiveRoom as setUIActiveRoom } from '@store/slices/uiSlice'
import api from '@services/api'
import socketService from '@services/socket'
import ChatHeader from './ChatHeader'
import MessageList from './MessageList'
import MessageInput from './MessageInput'

export default function ChatWindow() {
  const { roomId } = useParams()
  const dispatch = useAppDispatch()
  const { activeRoom, messages } = useAppSelector((state) => state.chat)
  const { rooms } = useAppSelector((state) => state.chat)
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    if (!roomId) {
      dispatch(setActiveRoom(null))
      dispatch(setUIActiveRoom(null))
      return
    }

    const loadRoomAndMessages = async () => {
      setIsLoading(true)
      try {
        // 채팅방 정보 로드
        const room = rooms.find((r) => r.id === roomId)
        if (room) {
          dispatch(setActiveRoom(room))
          dispatch(setUIActiveRoom(roomId))
        } else {
          const roomData = await api.getRoom(roomId)
          dispatch(setActiveRoom(roomData))
          dispatch(setUIActiveRoom(roomId))
        }

        // 메시지 로드
        const messagesData = await api.getMessages(roomId)
        dispatch(setMessages({ roomId, messages: messagesData }))

        // 소켓 룸 입장
        socketService.joinRoom(roomId)
      } catch (error) {
        console.error('Failed to load room:', error)
      } finally {
        setIsLoading(false)
      }
    }

    loadRoomAndMessages()

    return () => {
      if (roomId) {
        socketService.leaveRoom(roomId)
      }
    }
  }, [roomId, dispatch, rooms])

  if (!roomId) {
    return (
      <div className="flex-1 flex items-center justify-center bg-gray-50 dark:bg-gray-900">
        <div className="text-center">
          <div className="w-24 h-24 bg-gray-200 dark:bg-gray-700 rounded-full flex items-center justify-center mx-auto mb-4">
            <svg
              className="w-12 h-12 text-gray-400"
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
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
            KakaoChat에 오신 것을 환영합니다
          </h2>
          <p className="text-gray-600 dark:text-gray-400">
            채팅방을 선택하거나 새로운 채팅을 시작하세요
          </p>
        </div>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-primary-500"></div>
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col h-full bg-gray-50 dark:bg-gray-900">
      <ChatHeader room={activeRoom} />
      <MessageList messages={messages[roomId] || []} roomId={roomId} />
      <MessageInput roomId={roomId} />
    </div>
  )
}
