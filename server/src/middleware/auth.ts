import { Response, NextFunction } from 'express'
import { AuthRequest } from '../types'
import { verifyAccessToken } from '../utils/jwt'

export const authenticate = async (
  req: AuthRequest,
  res: Response,
  next: NextFunction
) => {
  try {
    const authHeader = req.headers.authorization

    if (!authHeader || !authHeader.startsWith('Bearer ')) {
      return res.status(401).json({
        success: false,
        message: '인증 토큰이 필요합니다.',
      })
    }

    const token = authHeader.substring(7)

    try {
      const decoded = verifyAccessToken(token)
      req.user = decoded
      next()
    } catch (error: any) {
      if (error.name === 'TokenExpiredError') {
        return res.status(401).json({
          success: false,
          message: '토큰이 만료되었습니다.',
        })
      }
      return res.status(401).json({
        success: false,
        message: '유효하지 않은 토큰입니다.',
      })
    }
  } catch (error) {
    console.error('Auth middleware error:', error)
    return res.status(500).json({
      success: false,
      message: '서버 오류가 발생했습니다.',
    })
  }
}
