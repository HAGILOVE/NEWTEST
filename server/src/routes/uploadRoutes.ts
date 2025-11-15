import { Router } from 'express'
import * as uploadController from '../controllers/uploadController'
import { authenticate } from '../middleware/auth'
import { upload } from '../config/multer'

const router = Router()

// 프로필 사진 업로드
router.post(
  '/avatar',
  authenticate,
  upload.single('avatar'),
  uploadController.uploadAvatar
)

// 파일 업로드
router.post(
  '/file',
  authenticate,
  upload.single('file'),
  uploadController.uploadFile
)

export default router
