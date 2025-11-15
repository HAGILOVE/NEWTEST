import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import { ChatRoom, Message } from '@types/index'

interface ChatState {
  rooms: ChatRoom[]
  messages: Record<string, Message[]>
  activeRoom: ChatRoom | null
}

const initialState: ChatState = {
  rooms: [],
  messages: {},
  activeRoom: null,
}

const chatSlice = createSlice({
  name: 'chat',
  initialState,
  reducers: {
    setRooms: (state, action: PayloadAction<ChatRoom[]>) => {
      state.rooms = action.payload
    },
    addRoom: (state, action: PayloadAction<ChatRoom>) => {
      const exists = state.rooms.find((room) => room.id === action.payload.id)
      if (!exists) {
        state.rooms.unshift(action.payload)
      }
    },
    updateRoom: (state, action: PayloadAction<ChatRoom>) => {
      const index = state.rooms.findIndex(
        (room) => room.id === action.payload.id
      )
      if (index !== -1) {
        state.rooms[index] = action.payload
        // 최근 메시지가 있는 방을 상단으로 이동
        const room = state.rooms.splice(index, 1)[0]
        state.rooms.unshift(room)
      }
    },
    setActiveRoom: (state, action: PayloadAction<ChatRoom | null>) => {
      state.activeRoom = action.payload
      if (action.payload) {
        // 활성 방의 읽지 않은 메시지 카운트 초기화
        const room = state.rooms.find((r) => r.id === action.payload.id)
        if (room) {
          room.unreadCount = 0
        }
      }
    },
    setMessages: (
      state,
      action: PayloadAction<{ roomId: string; messages: Message[] }>
    ) => {
      state.messages[action.payload.roomId] = action.payload.messages
    },
    addMessage: (state, action: PayloadAction<Message>) => {
      const { roomId } = action.payload
      if (!state.messages[roomId]) {
        state.messages[roomId] = []
      }
      // 중복 메시지 방지
      const exists = state.messages[roomId].find(
        (msg) => msg.id === action.payload.id
      )
      if (!exists) {
        state.messages[roomId].push(action.payload)
      }

      // 채팅방 목록에서 lastMessage 업데이트
      const room = state.rooms.find((r) => r.id === roomId)
      if (room) {
        room.lastMessage = action.payload
        room.updatedAt = action.payload.createdAt

        // 활성 방이 아니면 unreadCount 증가
        if (state.activeRoom?.id !== roomId) {
          room.unreadCount += 1
        }

        // 해당 방을 목록 상단으로 이동
        const index = state.rooms.findIndex((r) => r.id === roomId)
        if (index > 0) {
          const [movedRoom] = state.rooms.splice(index, 1)
          state.rooms.unshift(movedRoom)
        }
      }
    },
    deleteMessage: (
      state,
      action: PayloadAction<{ roomId: string; messageId: string }>
    ) => {
      const { roomId, messageId } = action.payload
      if (state.messages[roomId]) {
        const message = state.messages[roomId].find((msg) => msg.id === messageId)
        if (message) {
          message.isDeleted = true
          message.content = '삭제된 메시지입니다.'
        }
      }
    },
    markMessageAsRead: (
      state,
      action: PayloadAction<{ roomId: string; messageId: string; userId: string }>
    ) => {
      const { roomId, messageId, userId } = action.payload
      if (state.messages[roomId]) {
        const message = state.messages[roomId].find((msg) => msg.id === messageId)
        if (message && !message.readBy.includes(userId)) {
          message.readBy.push(userId)
        }
      }
    },
  },
})

export const {
  setRooms,
  addRoom,
  updateRoom,
  setActiveRoom,
  setMessages,
  addMessage,
  deleteMessage,
  markMessageAsRead,
} = chatSlice.actions

export default chatSlice.reducer
