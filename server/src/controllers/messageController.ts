import { Response } from 'express'
import { prisma } from '../config/database'
import Message from '../models/Message'
import { AuthRequest } from '../types'

export const getMessages = async (req: AuthRequest, res: Response) => {
  try {
    const userId = req.user?.id
    const { roomId } = req.params
    const page = parseInt(req.query.page as string) || 1
    const limit = parseInt(req.query.limit as string) || 50

    // 멤버십 확인
    const membership = await prisma.chatRoomMember.findFirst({
      where: {
        roomId,
        userId,
      },
    })

    if (!membership) {
      return res.status(403).json({
        success: false,
        message: '이 채팅방에 접근할 권한이 없습니다.',
      })
    }

    // 메시지 조회
    const messages = await Message.find({ roomId })
      .sort({ createdAt: -1 })
      .skip((page - 1) * limit)
      .limit(limit)
      .lean()

    // 송신자 정보 추가
    const messagesWithSenders = await Promise.all(
      messages.map(async (msg) => {
        const sender = await prisma.user.findUnique({
          where: { id: msg.senderId },
          select: {
            id: true,
            username: true,
            profileImage: true,
          },
        })

        return {
          ...msg,
          sender,
        }
      })
    )

    // 역순으로 정렬 (시간순)
    messagesWithSenders.reverse()

    res.json(messagesWithSenders)
  } catch (error) {
    console.error('Get messages error:', error)
    res.status(500).json({
      success: false,
      message: '메시지를 불러오는 중 오류가 발생했습니다.',
    })
  }
}

export const sendMessage = async (req: AuthRequest, res: Response) => {
  try {
    const userId = req.user?.id
    const { roomId, content, type = 'text', replyToId } = req.body

    // 멤버십 확인
    const membership = await prisma.chatRoomMember.findFirst({
      where: {
        roomId,
        userId,
      },
    })

    if (!membership) {
      return res.status(403).json({
        success: false,
        message: '이 채팅방에 접근할 권한이 없습니다.',
      })
    }

    // 메시지 생성
    const message = await Message.create({
      roomId,
      senderId: userId!,
      type,
      content,
      replyTo: replyToId,
      readBy: [userId!],
    })

    // 채팅방 업데이트 시간 갱신
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

    res.status(201).json(messageWithSender)
  } catch (error) {
    console.error('Send message error:', error)
    res.status(500).json({
      success: false,
      message: '메시지 전송 중 오류가 발생했습니다.',
    })
  }
}

export const deleteMessage = async (req: AuthRequest, res: Response) => {
  try {
    const userId = req.user?.id
    const { id: messageId } = req.params

    const message = await Message.findById(messageId)

    if (!message) {
      return res.status(404).json({
        success: false,
        message: '메시지를 찾을 수 없습니다.',
      })
    }

    // 권한 확인 (송신자만 삭제 가능)
    if (message.senderId !== userId) {
      return res.status(403).json({
        success: false,
        message: '메시지를 삭제할 권한이 없습니다.',
      })
    }

    // 소프트 삭제
    message.isDeleted = true
    message.content = '삭제된 메시지입니다.'
    await message.save()

    res.json({
      success: true,
      message: '메시지가 삭제되었습니다.',
    })
  } catch (error) {
    console.error('Delete message error:', error)
    res.status(500).json({
      success: false,
      message: '메시지 삭제 중 오류가 발생했습니다.',
    })
  }
}

export const markAsRead = async (req: AuthRequest, res: Response) => {
  try {
    const userId = req.user?.id
    const { roomId, messageIds } = req.body

    if (!messageIds || messageIds.length === 0) {
      return res.json({
        success: true,
        message: '읽을 메시지가 없습니다.',
      })
    }

    // 메시지 읽음 처리
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

    // lastReadAt 업데이트
    await prisma.chatRoomMember.updateMany({
      where: {
        roomId,
        userId,
      },
      data: {
        lastReadAt: new Date(),
      },
    })

    res.json({
      success: true,
      message: '메시지를 읽음 처리했습니다.',
    })
  } catch (error) {
    console.error('Mark as read error:', error)
    res.status(500).json({
      success: false,
      message: '메시지 읽음 처리 중 오류가 발생했습니다.',
    })
  }
}
