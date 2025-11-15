import { Router } from 'express'
import { body } from 'express-validator'
import * as authController from '../controllers/authController'
import { authenticate } from '../middleware/auth'

const router = Router()

// 회원가입
router.post(
  '/register',
  [
    body('email').isEmail().withMessage('유효한 이메일을 입력해주세요.'),
    body('username')
      .trim()
      .isLength({ min: 2, max: 50 })
      .withMessage('사용자 이름은 2-50자 사이여야 합니다.'),
    body('password')
      .isLength({ min: 6 })
      .withMessage('비밀번호는 최소 6자 이상이어야 합니다.'),
  ],
  authController.register
)

// 로그인
router.post(
  '/login',
  [
    body('email').isEmail().withMessage('유효한 이메일을 입력해주세요.'),
    body('password').notEmpty().withMessage('비밀번호를 입력해주세요.'),
  ],
  authController.login
)

// 로그아웃
router.post('/logout', authenticate, authController.logout)

// 토큰 갱신
router.post('/refresh', authController.refreshAccessToken)

export default router
