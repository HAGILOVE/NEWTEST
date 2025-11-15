import { Router } from 'express'
import { body } from 'express-validator'
import * as roomController from '../controllers/roomController'
import { authenticate } from '../middleware/auth'

const router = Router()

// 채팅방 목록
router.get('/', authenticate, roomController.getRooms)

// 채팅방 생성
router.post(
  '/',
  authenticate,
  [
    body('type')
      .isIn(['DIRECT', 'GROUP'])
      .withMessage('type은 DIRECT 또는 GROUP이어야 합니다.'),
    body('memberIds')
      .isArray({ min: 1 })
      .withMessage('최소 1명의 멤버가 필요합니다.'),
  ],
  roomController.createRoom
)

// 채팅방 조회
router.get('/:id', authenticate, roomController.getRoom)

// 채팅방 나가기
router.delete('/:id/leave', authenticate, roomController.leaveRoom)

// 멤버 초대
router.post(
  '/:id/invite',
  authenticate,
  [
    body('userIds')
      .isArray({ min: 1 })
      .withMessage('최소 1명의 사용자를 선택해주세요.'),
  ],
  roomController.inviteToRoom
)

export default router
