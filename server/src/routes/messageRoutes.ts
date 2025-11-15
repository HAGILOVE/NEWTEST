import { Router } from 'express'
import { body } from 'express-validator'
import * as messageController from '../controllers/messageController'
import { authenticate } from '../middleware/auth'

const router = Router()

// 메시지 조회
router.get('/:roomId', authenticate, messageController.getMessages)

// 메시지 전송
router.post(
  '/',
  authenticate,
  [
    body('roomId').notEmpty().withMessage('채팅방 ID가 필요합니다.'),
    body('content').notEmpty().withMessage('메시지 내용이 필요합니다.'),
  ],
  messageController.sendMessage
)

// 메시지 삭제
router.delete('/:id', authenticate, messageController.deleteMessage)

// 메시지 읽음 처리
router.post('/read', authenticate, messageController.markAsRead)

export default router
