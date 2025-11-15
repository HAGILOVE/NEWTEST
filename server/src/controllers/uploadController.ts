import { Response } from 'express'
import { AuthRequest } from '../types'
import { prisma } from '../config/database'
import sharp from 'sharp'
import path from 'path'
import fs from 'fs'

export const uploadAvatar = async (req: AuthRequest, res: Response) => {
  try {
    const userId = req.user?.id
    const file = req.file

    if (!file) {
      return res.status(400).json({
        success: false,
        message: '파일이 업로드되지 않았습니다.',
      })
    }

    // 이미지 리사이징 (프로필 사진은 200x200)
    const resizedPath = file.path.replace(
      path.extname(file.path),
      '_resized' + path.extname(file.path)
    )

    await sharp(file.path)
      .resize(200, 200, {
        fit: 'cover',
        position: 'center',
      })
      .jpeg({ quality: 90 })
      .toFile(resizedPath)

    // 원본 파일 삭제
    fs.unlinkSync(file.path)

    // 파일 URL 생성
    const fileUrl = `/uploads/avatars/${path.basename(resizedPath)}`

    // 사용자 프로필 이미지 업데이트
    const user = await prisma.user.update({
      where: { id: userId },
      data: { profileImage: fileUrl },
      select: {
        id: true,
        email: true,
        username: true,
        phone: true,
        profileImage: true,
        statusMessage: true,
        isOnline: true,
        lastSeen: true,
        createdAt: true,
      },
    })

    res.json(user)
  } catch (error) {
    console.error('Upload avatar error:', error)
    res.status(500).json({
      success: false,
      message: '파일 업로드 중 오류가 발생했습니다.',
    })
  }
}

export const uploadFile = async (req: AuthRequest, res: Response) => {
  try {
    const userId = req.user?.id
    const file = req.file
    const { roomId } = req.body

    if (!file) {
      return res.status(400).json({
        success: false,
        message: '파일이 업로드되지 않았습니다.',
      })
    }

    if (!roomId) {
      return res.status(400).json({
        success: false,
        message: '채팅방 ID가 필요합니다.',
      })
    }

    // 멤버십 확인
    const membership = await prisma.chatRoomMember.findFirst({
      where: {
        roomId,
        userId,
      },
    })

    if (!membership) {
      // 파일 삭제
      fs.unlinkSync(file.path)
      return res.status(403).json({
        success: false,
        message: '이 채팅방에 접근할 권한이 없습니다.',
      })
    }

    // 이미지인 경우 리사이징
    let fileUrl = ''
    if (file.mimetype.startsWith('image/')) {
      const resizedPath = file.path.replace(
        path.extname(file.path),
        '_resized' + path.extname(file.path)
      )

      await sharp(file.path)
        .resize(1000, 1000, {
          fit: 'inside',
          withoutEnlargement: true,
        })
        .jpeg({ quality: 85 })
        .toFile(resizedPath)

      // 원본 파일 삭제
      fs.unlinkSync(file.path)
      fileUrl = `/uploads/images/${path.basename(resizedPath)}`
    } else {
      fileUrl = `/uploads/files/${path.basename(file.path)}`
    }

    res.json({
      success: true,
      fileUrl,
      fileName: file.originalname,
      fileSize: file.size,
      mimeType: file.mimetype,
    })
  } catch (error) {
    console.error('Upload file error:', error)
    // 에러 발생시 파일 삭제
    if (req.file?.path) {
      try {
        fs.unlinkSync(req.file.path)
      } catch (e) {}
    }
    res.status(500).json({
      success: false,
      message: '파일 업로드 중 오류가 발생했습니다.',
    })
  }
}
