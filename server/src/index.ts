import express from 'express'
import { createServer } from 'http'
import cors from 'cors'
import dotenv from 'dotenv'
import { prisma, connectMongoDB, connectRedis } from './config/database'
import { initializeSocket } from './socket'
import { errorHandler, notFound } from './middleware/errorHandler'

// Routes
import authRoutes from './routes/authRoutes'
import userRoutes from './routes/userRoutes'
import friendRoutes from './routes/friendRoutes'
import roomRoutes from './routes/roomRoutes'
import messageRoutes from './routes/messageRoutes'
import uploadRoutes from './routes/uploadRoutes'

// 환경 변수 로드
dotenv.config()

const app = express()
const httpServer = createServer(app)
const PORT = process.env.PORT || 5000

// 미들웨어
app.use(
  cors({
    origin: process.env.CLIENT_URL || 'http://localhost:3000',
    credentials: true,
  })
)
app.use(express.json())
app.use(express.urlencoded({ extended: true }))

// 정적 파일 제공 (업로드된 파일)
app.use('/uploads', express.static('uploads'))

// 라우트
app.use('/api/auth', authRoutes)
app.use('/api/users', userRoutes)
app.use('/api/friends', friendRoutes)
app.use('/api/rooms', roomRoutes)
app.use('/api/messages', messageRoutes)
app.use('/api/upload', uploadRoutes)

// 헬스 체크
app.get('/health', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() })
})

// 에러 핸들러
app.use(notFound)
app.use(errorHandler)

// Socket.IO 초기화
const io = initializeSocket(httpServer)

// 데이터베이스 연결 및 서버 시작
const startServer = async () => {
  try {
    // MongoDB 연결
    await connectMongoDB()

    // Redis 연결 (선택적)
    try {
      await connectRedis()
    } catch (error) {
      console.warn('⚠️  Redis connection failed, continuing without cache')
    }

    // Prisma 연결 확인
    await prisma.$connect()
    console.log('✅ PostgreSQL connected successfully')

    // 서버 시작
    httpServer.listen(PORT, () => {
      console.log(`
╔═══════════════════════════════════════╗
║   🚀 KakaoChat Server is running     ║
║                                       ║
║   📡 Port: ${PORT}                      ║
║   🌍 Environment: ${process.env.NODE_ENV || 'development'}      ║
║   📅 Started: ${new Date().toLocaleString()}  ║
╚═══════════════════════════════════════╝
      `)
    })
  } catch (error) {
    console.error('❌ Failed to start server:', error)
    process.exit(1)
  }
}

startServer()

// Graceful shutdown
process.on('SIGTERM', async () => {
  console.log('SIGTERM received, shutting down gracefully...')
  httpServer.close(async () => {
    await prisma.$disconnect()
    process.exit(0)
  })
})

process.on('SIGINT', async () => {
  console.log('\nSIGINT received, shutting down gracefully...')
  httpServer.close(async () => {
    await prisma.$disconnect()
    process.exit(0)
  })
})
