import { PrismaClient } from '@prisma/client'
import mongoose from 'mongoose'
import { createClient } from 'redis'

// Prisma Client (PostgreSQL)
export const prisma = new PrismaClient({
  log: process.env.NODE_ENV === 'development' ? ['query', 'error', 'warn'] : ['error'],
})

// MongoDB Connection
export const connectMongoDB = async () => {
  try {
    const mongoUri = process.env.MONGODB_URI || 'mongodb://localhost:27017/kakaochat'
    await mongoose.connect(mongoUri)
    console.log('✅ MongoDB connected successfully')
  } catch (error) {
    console.error('❌ MongoDB connection error:', error)
    process.exit(1)
  }
}

// Redis Client
export const redisClient = createClient({
  url: process.env.REDIS_URL || 'redis://localhost:6379',
})

export const connectRedis = async () => {
  try {
    await redisClient.connect()
    console.log('✅ Redis connected successfully')
  } catch (error) {
    console.error('❌ Redis connection error:', error)
    console.log('⚠️  Continuing without Redis (caching disabled)')
  }
}

// Graceful shutdown
process.on('SIGINT', async () => {
  await prisma.$disconnect()
  await mongoose.disconnect()
  await redisClient.quit()
  process.exit(0)
})
