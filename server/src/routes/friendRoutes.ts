import { Router } from 'express'
import { body } from 'express-validator'
import * as friendController from '../controllers/friendController'
import { authenticate } from '../middleware/auth'

const router = Router()

// 친구 목록
router.get('/', authenticate, friendController.getFriends)

// 친구 추가
router.post(
  '/',
  authenticate,
  [body('userId').notEmpty().withMessage('사용자 ID가 필요합니다.')],
  friendController.addFriend
)

// 친구 삭제
router.delete('/:id', authenticate, friendController.removeFriend)

// 즐겨찾기 토글
router.put('/:id/favorite', authenticate, friendController.toggleFavorite)

export default router
