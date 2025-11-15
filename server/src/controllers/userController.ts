import { Response } from 'express'
import { prisma } from '../config/database'
import { AuthRequest } from '../types'

export const getCurrentUser = async (req: AuthRequest, res: Response) => {
  try {
    const userId = req.user?.id

    const user = await prisma.user.findUnique({
      where: { id: userId },
      select: {
        id: true,
        email: true,
        username: true,
        phone: true,
        profileImage: true,
        statusMessage: true,
        isOnline: true,
        lastSeen: true,
        createdAt: true,
      },
    })

    if (!user) {
      return res.status(404).json({
        success: false,
        message: '사용자를 찾을 수 없습니다.',
      })
    }

    res.json(user)
  } catch (error) {
    console.error('Get current user error:', error)
    res.status(500).json({
      success: false,
      message: '사용자 정보를 불러오는 중 오류가 발생했습니다.',
    })
  }
}

export const updateProfile = async (req: AuthRequest, res: Response) => {
  try {
    const userId = req.user?.id
    const { username, statusMessage, profileImage } = req.body

    const updatedUser = await prisma.user.update({
      where: { id: userId },
      data: {
        ...(username && { username }),
        ...(statusMessage !== undefined && { statusMessage }),
        ...(profileImage !== undefined && { profileImage }),
      },
      select: {
        id: true,
        email: true,
        username: true,
        phone: true,
        profileImage: true,
        statusMessage: true,
        isOnline: true,
        lastSeen: true,
        createdAt: true,
      },
    })

    res.json(updatedUser)
  } catch (error) {
    console.error('Update profile error:', error)
    res.status(500).json({
      success: false,
      message: '프로필 업데이트 중 오류가 발생했습니다.',
    })
  }
}

export const searchUsers = async (req: AuthRequest, res: Response) => {
  try {
    const { q } = req.query
    const currentUserId = req.user?.id

    if (!q || typeof q !== 'string') {
      return res.status(400).json({
        success: false,
        message: '검색어를 입력해주세요.',
      })
    }

    const users = await prisma.user.findMany({
      where: {
        AND: [
          { id: { not: currentUserId } },
          {
            OR: [
              { username: { contains: q, mode: 'insensitive' } },
              { email: { contains: q, mode: 'insensitive' } },
            ],
          },
        ],
      },
      select: {
        id: true,
        email: true,
        username: true,
        profileImage: true,
        statusMessage: true,
        isOnline: true,
      },
      take: 20,
    })

    res.json(users)
  } catch (error) {
    console.error('Search users error:', error)
    res.status(500).json({
      success: false,
      message: '사용자 검색 중 오류가 발생했습니다.',
    })
  }
}

export const getUserById = async (req: AuthRequest, res: Response) => {
  try {
    const { id } = req.params

    const user = await prisma.user.findUnique({
      where: { id },
      select: {
        id: true,
        email: true,
        username: true,
        profileImage: true,
        statusMessage: true,
        isOnline: true,
        lastSeen: true,
      },
    })

    if (!user) {
      return res.status(404).json({
        success: false,
        message: '사용자를 찾을 수 없습니다.',
      })
    }

    res.json(user)
  } catch (error) {
    console.error('Get user error:', error)
    res.status(500).json({
      success: false,
      message: '사용자 정보를 불러오는 중 오류가 발생했습니다.',
    })
  }
}
