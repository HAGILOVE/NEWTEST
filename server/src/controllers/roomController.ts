import { Response } from 'express'
import { prisma } from '../config/database'
import Message from '../models/Message'
import { AuthRequest, CreateRoomData } from '../types'

export const getRooms = async (req: AuthRequest, res: Response) => {
  try {
    const userId = req.user?.id

    const roomMemberships = await prisma.chatRoomMember.findMany({
      where: { userId },
      include: {
        room: {
          include: {
            members: {
              include: {
                user: {
                  select: {
                    id: true,
                    username: true,
                    profileImage: true,
                    isOnline: true,
                    statusMessage: true,
                  },
                },
              },
            },
          },
        },
      },
      orderBy: {
        room: {
          updatedAt: 'desc',
        },
      },
    })

    // 각 방의 마지막 메시지와 읽지 않은 메시지 수 가져오기
    const rooms = await Promise.all(
      roomMemberships.map(async (membership) => {
        const room = membership.room

        // 마지막 메시지
        const lastMessage = await Message.findOne({ roomId: room.id })
          .sort({ createdAt: -1 })
          .lean()

        // 읽지 않은 메시지 수
        const unreadCount = await Message.countDocuments({
          roomId: room.id,
          createdAt: { $gt: membership.lastReadAt || new Date(0) },
          senderId: { $ne: userId },
        })

        // 1:1 채팅의 경우 상대방 정보만 포함
        let members = room.members.map((m) => m.user)
        if (room.type === 'DIRECT') {
          members = members.filter((m) => m.id !== userId)
        }

        return {
          id: room.id,
          name: room.name,
          type: room.type.toLowerCase(),
          members,
          lastMessage,
          unreadCount,
          createdBy: room.createdBy,
          createdAt: room.createdAt,
          updatedAt: room.updatedAt,
        }
      })
    )

    res.json(rooms)
  } catch (error) {
    console.error('Get rooms error:', error)
    res.status(500).json({
      success: false,
      message: '채팅방 목록을 불러오는 중 오류가 발생했습니다.',
    })
  }
}

export const createRoom = async (req: AuthRequest, res: Response) => {
  try {
    const userId = req.user?.id
    const { type, memberIds, name }: CreateRoomData = req.body

    if (!memberIds || memberIds.length === 0) {
      return res.status(400).json({
        success: false,
        message: '최소 1명의 멤버가 필요합니다.',
      })
    }

    // 1:1 채팅의 경우 기존 방 확인
    if (type === 'DIRECT' && memberIds.length === 1) {
      const existingRoom = await prisma.chatRoom.findFirst({
        where: {
          type: 'DIRECT',
          members: {
            every: {
              OR: [{ userId: userId! }, { userId: memberIds[0] }],
            },
          },
        },
        include: {
          members: {
            include: {
              user: {
                select: {
                  id: true,
                  username: true,
                  profileImage: true,
                  isOnline: true,
                  statusMessage: true,
                },
              },
            },
          },
        },
      })

      if (existingRoom) {
        return res.json(existingRoom)
      }
    }

    // 새 채팅방 생성
    const allMemberIds = [userId!, ...memberIds]

    const room = await prisma.chatRoom.create({
      data: {
        type,
        name: type === 'GROUP' ? name : undefined,
        createdBy: userId!,
        members: {
          create: allMemberIds.map((memberId, index) => ({
            userId: memberId,
            role: memberId === userId ? 'ADMIN' : 'MEMBER',
          })),
        },
      },
      include: {
        members: {
          include: {
            user: {
              select: {
                id: true,
                username: true,
                profileImage: true,
                isOnline: true,
                statusMessage: true,
              },
            },
          },
        },
      },
    })

    res.status(201).json(room)
  } catch (error) {
    console.error('Create room error:', error)
    res.status(500).json({
      success: false,
      message: '채팅방 생성 중 오류가 발생했습니다.',
    })
  }
}

export const getRoom = async (req: AuthRequest, res: Response) => {
  try {
    const userId = req.user?.id
    const { id } = req.params

    const room = await prisma.chatRoom.findUnique({
      where: { id },
      include: {
        members: {
          include: {
            user: {
              select: {
                id: true,
                username: true,
                profileImage: true,
                isOnline: true,
                statusMessage: true,
              },
            },
          },
        },
      },
    })

    if (!room) {
      return res.status(404).json({
        success: false,
        message: '채팅방을 찾을 수 없습니다.',
      })
    }

    // 멤버 확인
    const isMember = room.members.some((m) => m.userId === userId)
    if (!isMember) {
      return res.status(403).json({
        success: false,
        message: '이 채팅방에 접근할 권한이 없습니다.',
      })
    }

    res.json(room)
  } catch (error) {
    console.error('Get room error:', error)
    res.status(500).json({
      success: false,
      message: '채팅방 정보를 불러오는 중 오류가 발생했습니다.',
    })
  }
}

export const leaveRoom = async (req: AuthRequest, res: Response) => {
  try {
    const userId = req.user?.id
    const { id: roomId } = req.params

    const membership = await prisma.chatRoomMember.findFirst({
      where: {
        roomId,
        userId,
      },
    })

    if (!membership) {
      return res.status(404).json({
        success: false,
        message: '채팅방을 찾을 수 없습니다.',
      })
    }

    await prisma.chatRoomMember.delete({
      where: { id: membership.id },
    })

    // 남은 멤버가 없으면 채팅방 삭제
    const remainingMembers = await prisma.chatRoomMember.count({
      where: { roomId },
    })

    if (remainingMembers === 0) {
      await prisma.chatRoom.delete({
        where: { id: roomId },
      })
      await Message.deleteMany({ roomId })
    }

    res.json({
      success: true,
      message: '채팅방을 나갔습니다.',
    })
  } catch (error) {
    console.error('Leave room error:', error)
    res.status(500).json({
      success: false,
      message: '채팅방 나가기 중 오류가 발생했습니다.',
    })
  }
}

export const inviteToRoom = async (req: AuthRequest, res: Response) => {
  try {
    const userId = req.user?.id
    const { id: roomId } = req.params
    const { userIds } = req.body

    if (!userIds || userIds.length === 0) {
      return res.status(400).json({
        success: false,
        message: '초대할 사용자를 선택해주세요.',
      })
    }

    // 방 확인 및 권한 체크
    const room = await prisma.chatRoom.findUnique({
      where: { id: roomId },
      include: { members: true },
    })

    if (!room) {
      return res.status(404).json({
        success: false,
        message: '채팅방을 찾을 수 없습니다.',
      })
    }

    const isMember = room.members.some((m) => m.userId === userId)
    if (!isMember) {
      return res.status(403).json({
        success: false,
        message: '권한이 없습니다.',
      })
    }

    // 멤버 추가
    await prisma.chatRoomMember.createMany({
      data: userIds.map((uid: string) => ({
        roomId,
        userId: uid,
        role: 'MEMBER',
      })),
      skipDuplicates: true,
    })

    res.json({
      success: true,
      message: '사용자를 초대했습니다.',
    })
  } catch (error) {
    console.error('Invite to room error:', error)
    res.status(500).json({
      success: false,
      message: '사용자 초대 중 오류가 발생했습니다.',
    })
  }
}
