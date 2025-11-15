import { io, Socket } from 'socket.io-client'
import {
  Message,
  TypingEvent,
  OnlineStatusEvent,
  MessageReadEvent,
} from '@types/index'

const SOCKET_URL = import.meta.env.VITE_SOCKET_URL || 'http://localhost:5000'

class SocketService {
  private socket: Socket | null = null
  private listeners: Map<string, Set<Function>> = new Map()

  connect(token: string) {
    if (this.socket?.connected) {
      return
    }

    this.socket = io(SOCKET_URL, {
      auth: {
        token,
      },
      reconnection: true,
      reconnectionAttempts: 5,
      reconnectionDelay: 1000,
    })

    this.socket.on('connect', () => {
      console.log('Socket connected:', this.socket?.id)
    })

    this.socket.on('disconnect', (reason) => {
      console.log('Socket disconnected:', reason)
    })

    this.socket.on('connect_error', (error) => {
      console.error('Socket connection error:', error)
    })

    // 메시지 이벤트
    this.socket.on('new_message', (message: Message) => {
      this.emit('new_message', message)
    })

    // 메시지 삭제 이벤트
    this.socket.on(
      'message_deleted',
      (data: { roomId: string; messageId: string }) => {
        this.emit('message_deleted', data)
      }
    )

    // 타이핑 이벤트
    this.socket.on('user_typing', (data: TypingEvent) => {
      this.emit('user_typing', data)
    })

    // 읽음 표시 이벤트
    this.socket.on('message_read', (data: MessageReadEvent) => {
      this.emit('message_read', data)
    })

    // 온라인 상태 이벤트
    this.socket.on('user_online', (data: OnlineStatusEvent) => {
      this.emit('user_online', data)
    })

    this.socket.on('user_offline', (data: OnlineStatusEvent) => {
      this.emit('user_offline', data)
    })
  }

  disconnect() {
    if (this.socket) {
      this.socket.disconnect()
      this.socket = null
      this.listeners.clear()
    }
  }

  // 채팅방 입장
  joinRoom(roomId: string) {
    this.socket?.emit('join_room', { roomId })
  }

  // 채팅방 퇴장
  leaveRoom(roomId: string) {
    this.socket?.emit('leave_room', { roomId })
  }

  // 메시지 전송
  sendMessage(data: {
    roomId: string
    content: string
    type?: string
    replyToId?: string
  }) {
    this.socket?.emit('send_message', data)
  }

  // 타이핑 시작
  startTyping(roomId: string) {
    this.socket?.emit('typing_start', { roomId })
  }

  // 타이핑 종료
  stopTyping(roomId: string) {
    this.socket?.emit('typing_stop', { roomId })
  }

  // 메시지 읽음 처리
  markAsRead(roomId: string, messageIds: string[]) {
    this.socket?.emit('mark_read', { roomId, messageIds })
  }

  // 이벤트 리스너 등록
  on(event: string, callback: Function) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set())
    }
    this.listeners.get(event)?.add(callback)
  }

  // 이벤트 리스너 제거
  off(event: string, callback?: Function) {
    if (!callback) {
      this.listeners.delete(event)
      return
    }
    this.listeners.get(event)?.delete(callback)
  }

  // 이벤트 발생
  private emit(event: string, data: any) {
    this.listeners.get(event)?.forEach((callback) => {
      callback(data)
    })
  }

  isConnected() {
    return this.socket?.connected || false
  }
}

export default new SocketService()
