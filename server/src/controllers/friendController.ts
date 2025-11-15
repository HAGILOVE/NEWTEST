import { Response } from 'express'
import { prisma } from '../config/database'
import { AuthRequest } from '../types'

export const getFriends = async (req: AuthRequest, res: Response) => {
  try {
    const userId = req.user?.id

    const friendships = await prisma.friend.findMany({
      where: { userId },
      include: {
        friend: {
          select: {
            id: true,
            email: true,
            username: true,
            profileImage: true,
            statusMessage: true,
            isOnline: true,
            lastSeen: true,
          },
        },
      },
      orderBy: [{ isFavorite: 'desc' }, { createdAt: 'desc' }],
    })

    const friends = friendships.map((f) => ({
      ...f.friend,
      friendshipId: f.id,
      isFavorite: f.isFavorite,
    }))

    res.json(friends)
  } catch (error) {
    console.error('Get friends error:', error)
    res.status(500).json({
      success: false,
      message: '친구 목록을 불러오는 중 오류가 발생했습니다.',
    })
  }
}

export const addFriend = async (req: AuthRequest, res: Response) => {
  try {
    const userId = req.user?.id
    const { userId: friendId } = req.body

    if (userId === friendId) {
      return res.status(400).json({
        success: false,
        message: '자기 자신을 친구로 추가할 수 없습니다.',
      })
    }

    // 친구 사용자 확인
    const friendUser = await prisma.user.findUnique({
      where: { id: friendId },
    })

    if (!friendUser) {
      return res.status(404).json({
        success: false,
        message: '사용자를 찾을 수 없습니다.',
      })
    }

    // 이미 친구인지 확인
    const existingFriendship = await prisma.friend.findUnique({
      where: {
        userId_friendId: {
          userId: userId!,
          friendId,
        },
      },
    })

    if (existingFriendship) {
      return res.status(400).json({
        success: false,
        message: '이미 친구입니다.',
      })
    }

    // 양방향 친구 관계 생성
    await prisma.$transaction([
      prisma.friend.create({
        data: {
          userId: userId!,
          friendId,
        },
      }),
      prisma.friend.create({
        data: {
          userId: friendId,
          friendId: userId!,
        },
      }),
    ])

    res.status(201).json({
      success: true,
      message: '친구가 추가되었습니다.',
    })
  } catch (error) {
    console.error('Add friend error:', error)
    res.status(500).json({
      success: false,
      message: '친구 추가 중 오류가 발생했습니다.',
    })
  }
}

export const removeFriend = async (req: AuthRequest, res: Response) => {
  try {
    const userId = req.user?.id
    const { id: friendshipId } = req.params

    const friendship = await prisma.friend.findUnique({
      where: { id: friendshipId },
    })

    if (!friendship || friendship.userId !== userId) {
      return res.status(404).json({
        success: false,
        message: '친구 관계를 찾을 수 없습니다.',
      })
    }

    // 양방향 친구 관계 삭제
    await prisma.$transaction([
      prisma.friend.delete({
        where: { id: friendshipId },
      }),
      prisma.friend.deleteMany({
        where: {
          userId: friendship.friendId,
          friendId: userId!,
        },
      }),
    ])

    res.json({
      success: true,
      message: '친구가 삭제되었습니다.',
    })
  } catch (error) {
    console.error('Remove friend error:', error)
    res.status(500).json({
      success: false,
      message: '친구 삭제 중 오류가 발생했습니다.',
    })
  }
}

export const toggleFavorite = async (req: AuthRequest, res: Response) => {
  try {
    const userId = req.user?.id
    const { id: friendshipId } = req.params

    const friendship = await prisma.friend.findUnique({
      where: { id: friendshipId },
    })

    if (!friendship || friendship.userId !== userId) {
      return res.status(404).json({
        success: false,
        message: '친구 관계를 찾을 수 없습니다.',
      })
    }

    const updated = await prisma.friend.update({
      where: { id: friendshipId },
      data: {
        isFavorite: !friendship.isFavorite,
      },
    })

    res.json({
      success: true,
      isFavorite: updated.isFavorite,
    })
  } catch (error) {
    console.error('Toggle favorite error:', error)
    res.status(500).json({
      success: false,
      message: '즐겨찾기 업데이트 중 오류가 발생했습니다.',
    })
  }
}
