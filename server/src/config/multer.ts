import multer from 'multer'
import path from 'path'
import fs from 'fs'
import { v4 as uuidv4 } from 'uuid'

// uploads 디렉토리 생성
const uploadDir = process.env.UPLOAD_DIR || './uploads'
const dirs = ['avatars', 'images', 'files']

dirs.forEach((dir) => {
  const fullPath = path.join(uploadDir, dir)
  if (!fs.existsSync(fullPath)) {
    fs.mkdirSync(fullPath, { recursive: true })
  }
})

// 파일 저장 설정
const storage = multer.diskStorage({
  destination: (req, file, cb) => {
    let folder = 'files'
    if (file.fieldname === 'avatar') {
      folder = 'avatars'
    } else if (file.mimetype.startsWith('image/')) {
      folder = 'images'
    }
    cb(null, path.join(uploadDir, folder))
  },
  filename: (req, file, cb) => {
    const uniqueName = `${uuidv4()}${path.extname(file.originalname)}`
    cb(null, uniqueName)
  },
})

// 파일 필터
const fileFilter = (req: any, file: Express.Multer.File, cb: any) => {
  // 허용되는 파일 타입
  const allowedMimes = [
    'image/jpeg',
    'image/jpg',
    'image/png',
    'image/gif',
    'image/webp',
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'text/plain',
    'application/zip',
  ]

  if (allowedMimes.includes(file.mimetype)) {
    cb(null, true)
  } else {
    cb(new Error('지원하지 않는 파일 형식입니다.'))
  }
}

export const upload = multer({
  storage,
  fileFilter,
  limits: {
    fileSize: parseInt(process.env.MAX_FILE_SIZE || '104857600'), // 100MB
  },
})
