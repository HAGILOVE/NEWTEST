import { Request } from 'express'

export interface AuthRequest extends Request {
  user?: {
    id: string
    email: string
    username: string
  }
}

export interface CreateRoomData {
  type: 'DIRECT' | 'GROUP'
  memberIds: string[]
  name?: string
}

export interface SendMessageData {
  roomId: string
  content: string
  type?: 'text' | 'image' | 'file' | 'voice'
  replyToId?: string
}

export interface SocketUser {
  userId: string
  socketId: string
}

export interface TypingData {
  roomId: string
  userId: string
  username: string
  isTyping: boolean
}

export interface MessageReadData {
  messageId: string
  roomId: string
  userId: string
  readAt: Date
}
