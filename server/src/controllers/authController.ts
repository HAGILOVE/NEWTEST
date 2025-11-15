import { Response } from 'express'
import bcrypt from 'bcryptjs'
import { prisma } from '../config/database'
import { AuthRequest } from '../types'
import {
  generateAccessToken,
  generateRefreshToken,
  verifyRefreshToken,
} from '../utils/jwt'

export const register = async (req: AuthRequest, res: Response) => {
  try {
    const { email, username, password, phone } = req.body

    // 이메일 중복 체크
    const existingUser = await prisma.user.findUnique({
      where: { email },
    })

    if (existingUser) {
      return res.status(400).json({
        success: false,
        message: '이미 사용 중인 이메일입니다.',
      })
    }

    // 전화번호 중복 체크
    if (phone) {
      const existingPhone = await prisma.user.findUnique({
        where: { phone },
      })

      if (existingPhone) {
        return res.status(400).json({
          success: false,
          message: '이미 사용 중인 전화번호입니다.',
        })
      }
    }

    // 비밀번호 해싱
    const hashedPassword = await bcrypt.hash(password, 10)

    // 사용자 생성
    const user = await prisma.user.create({
      data: {
        email,
        username,
        password: hashedPassword,
        phone,
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

    // 토큰 생성
    const accessToken = generateAccessToken({
      id: user.id,
      email: user.email,
      username: user.username,
    })

    const refreshToken = generateRefreshToken({
      id: user.id,
      email: user.email,
      username: user.username,
    })

    // Refresh token 저장
    const expiresAt = new Date()
    expiresAt.setDate(expiresAt.getDate() + 7)

    await prisma.refreshToken.create({
      data: {
        userId: user.id,
        token: refreshToken,
        expiresAt,
      },
    })

    res.status(201).json({
      success: true,
      user,
      accessToken,
      refreshToken,
    })
  } catch (error) {
    console.error('Register error:', error)
    res.status(500).json({
      success: false,
      message: '회원가입 중 오류가 발생했습니다.',
    })
  }
}

export const login = async (req: AuthRequest, res: Response) => {
  try {
    const { email, password } = req.body

    // 사용자 찾기
    const user = await prisma.user.findUnique({
      where: { email },
    })

    if (!user) {
      return res.status(401).json({
        success: false,
        message: '이메일 또는 비밀번호가 올바르지 않습니다.',
      })
    }

    // 비밀번호 확인
    const isPasswordValid = await bcrypt.compare(password, user.password)

    if (!isPasswordValid) {
      return res.status(401).json({
        success: false,
        message: '이메일 또는 비밀번호가 올바르지 않습니다.',
      })
    }

    // 온라인 상태 업데이트
    await prisma.user.update({
      where: { id: user.id },
      data: { isOnline: true },
    })

    // 토큰 생성
    const accessToken = generateAccessToken({
      id: user.id,
      email: user.email,
      username: user.username,
    })

    const refreshToken = generateRefreshToken({
      id: user.id,
      email: user.email,
      username: user.username,
    })

    // Refresh token 저장
    const expiresAt = new Date()
    expiresAt.setDate(expiresAt.getDate() + 7)

    await prisma.refreshToken.create({
      data: {
        userId: user.id,
        token: refreshToken,
        expiresAt,
      },
    })

    const { password: _, ...userWithoutPassword } = user

    res.json({
      success: true,
      user: { ...userWithoutPassword, isOnline: true },
      accessToken,
      refreshToken,
    })
  } catch (error) {
    console.error('Login error:', error)
    res.status(500).json({
      success: false,
      message: '로그인 중 오류가 발생했습니다.',
    })
  }
}

export const logout = async (req: AuthRequest, res: Response) => {
  try {
    const userId = req.user?.id

    if (userId) {
      // 온라인 상태 업데이트
      await prisma.user.update({
        where: { id: userId },
        data: {
          isOnline: false,
          lastSeen: new Date(),
        },
      })

      // Refresh tokens 삭제
      await prisma.refreshToken.deleteMany({
        where: { userId },
      })
    }

    res.json({
      success: true,
      message: '로그아웃되었습니다.',
    })
  } catch (error) {
    console.error('Logout error:', error)
    res.status(500).json({
      success: false,
      message: '로그아웃 중 오류가 발생했습니다.',
    })
  }
}

export const refreshAccessToken = async (req: AuthRequest, res: Response) => {
  try {
    const { refreshToken } = req.body

    if (!refreshToken) {
      return res.status(401).json({
        success: false,
        message: 'Refresh token이 필요합니다.',
      })
    }

    // Refresh token 검증
    const decoded = verifyRefreshToken(refreshToken)

    // DB에서 token 확인
    const storedToken = await prisma.refreshToken.findUnique({
      where: { token: refreshToken },
    })

    if (!storedToken || storedToken.expiresAt < new Date()) {
      return res.status(401).json({
        success: false,
        message: '유효하지 않거나 만료된 refresh token입니다.',
      })
    }

    // 새로운 access token 생성
    const accessToken = generateAccessToken({
      id: decoded.id,
      email: decoded.email,
      username: decoded.username,
    })

    res.json({
      success: true,
      accessToken,
    })
  } catch (error) {
    console.error('Refresh token error:', error)
    res.status(401).json({
      success: false,
      message: 'Token 갱신에 실패했습니다.',
    })
  }
}
