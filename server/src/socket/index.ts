import { Server as SocketIOServer } from 'socket.io'
import { Server as HTTPServer } from 'http'
import { verifyAccessToken } from '../utils/jwt'
import { prisma } from '../config/database'
import Message from '../models/Message'

interface SocketUser {
  userId: string
  socketId: string
}

const onlineUsers: Map<string, Set<string>> = new Map() // userId -> Set of socketIds

export const initializeSocket = (httpServer: HTTPServer) => {
  const io = new SocketIOServer(httpServer, {
    cors: {
      origin: process.env.CLIENT_URL || 'http://localhost:3000',
      credentials: true,
    },
  })

  // 인증 미들웨어
  io.use((socket, next) => {
    try {
      const token = socket.handshake.auth.token

      if (!token) {
        return next(new Error('인증 토큰이 필요합니다.'))
      }

      const decoded = verifyAccessToken(token)
      socket.data.user = decoded
      next()
    } catch (error) {
      next(new Error('유효하지 않은 토큰입니다.'))
    }
  })

  io.on('connection', async (socket) => {
    const userId = socket.data.user.id
    console.log(`✅ User connected: ${userId} (${socket.id})`)

    // 온라인 사용자 추가
    if (!onlineUsers.has(userId)) {
      onlineUsers.set(userId, new Set())
    }
    onlineUsers.get(userId)!.add(socket.id)

    // 사용자 온라인 상태 업데이트
    await prisma.user.update({
      where: { id: userId },
      data: { isOnline: true },
    })

    // 친구들에게 온라인 상태 알림
    const friends = await prisma.friend.findMany({
      where: { friendId: userId },
      select: { userId: true },
    })

    friends.forEach((friend) => {
      const friendSocketIds = onlineUsers.get(friend.userId)
      if (friendSocketIds) {
        friendSocketIds.forEach((socketId) => {
          io.to(socketId).emit('user_online', {
            userId,
            isOnline: true,
          })
        })
      }
    })

    // 채팅방 입장
    socket.on('join_room', ({ roomId }) => {
      socket.join(roomId)
      console.log(`📝 User ${userId} joined room ${roomId}`)
    })

    // 채팅방 퇴장
    socket.on('leave_room', ({ roomId }) => {
      socket.leave(roomId)
      console.log(`📤 User ${userId} left room ${roomId}`)
    })

    // 메시지 전송
    socket.on('send_message', async (data) => {
      try {
        const { roomId, content, type = 'text', replyToId } = data

        // 메시지 생성
        const message = await Message.create({
          roomId,
          senderId: userId,
          type,
          content,
          replyTo: replyToId,
          readBy: [userId],
        })

        // 채팅방 업데이트
        await prisma.chatRoom.update({
          where: { id: roomId },
          data: { updatedAt: new Date() },
        })

        // 송신자 정보 추가
        const sender = await prisma.user.findUnique({
          where: { id: userId },
          select: {
            id: true,
            username: true,
            profileImage: true,
          },
        })

        const messageWithSender = {
          ...message.toObject(),
          sender,
        }

        // 채팅방 멤버들에게 메시지 전송
        io.to(roomId).emit('new_message', messageWithSender)
      } catch (error) {
        console.error('Send message error:', error)
        socket.emit('error', { message: '메시지 전송에 실패했습니다.' })
      }
    })

    // 타이핑 시작
    socket.on('typing_start', ({ roomId }) => {
      socket.to(roomId).emit('user_typing', {
        roomId,
        userId,
        username: socket.data.user.username,
        isTyping: true,
      })
    })

    // 타이핑 종료
    socket.on('typing_stop', ({ roomId }) => {
      socket.to(roomId).emit('user_typing', {
        roomId,
        userId,
        username: socket.data.user.username,
        isTyping: false,
      })
    })

    // 메시지 읽음 처리
    socket.on('mark_read', async ({ roomId, messageIds }) => {
      try {
        await Message.updateMany(
          {
            _id: { $in: messageIds },
            roomId,
            senderId: { $ne: userId },
          },
          {
            $addToSet: { readBy: userId },
          }
        )

        await prisma.chatRoomMember.updateMany({
          where: { roomId, userId },
          data: { lastReadAt: new Date() },
        })

        // 읽음 상태를 채팅방 멤버들에게 알림
        messageIds.forEach((messageId: string) => {
          io.to(roomId).emit('message_read', {
            messageId,
            roomId,
            userId,
            readAt: new Date(),
          })
        })
      } catch (error) {
        console.error('Mark read error:', error)
      }
    })

    // 연결 해제
    socket.on('disconnect', async () => {
      console.log(`❌ User disconnected: ${userId} (${socket.id})`)

      // 소켓 ID 제거
      const userSockets = onlineUsers.get(userId)
      if (userSockets) {
        userSockets.delete(socket.id)

        // 모든 소켓이 연결 해제되면 오프라인 처리
        if (userSockets.size === 0) {
          onlineUsers.delete(userId)

          await prisma.user.update({
            where: { id: userId },
            data: {
              isOnline: false,
              lastSeen: new Date(),
            },
          })

          // 친구들에게 오프라인 상태 알림
          const friends = await prisma.friend.findMany({
            where: { friendId: userId },
            select: { userId: true },
          })

          friends.forEach((friend) => {
            const friendSocketIds = onlineUsers.get(friend.userId)
            if (friendSocketIds) {
              friendSocketIds.forEach((socketId) => {
                io.to(socketId).emit('user_offline', {
                  userId,
                  isOnline: false,
                  lastSeen: new Date(),
                })
              })
            }
          })
        }
      }
    })
  })

  return io
}
