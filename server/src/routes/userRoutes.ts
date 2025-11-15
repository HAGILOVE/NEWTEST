import { Router } from 'express'
import * as userController from '../controllers/userController'
import { authenticate } from '../middleware/auth'

const router = Router()

// 현재 사용자 정보
router.get('/me', authenticate, userController.getCurrentUser)

// 프로필 업데이트
router.put('/me', authenticate, userController.updateProfile)

// 사용자 검색
router.get('/search', authenticate, userController.searchUsers)

// 사용자 조회
router.get('/:id', authenticate, userController.getUserById)

export default router
