import mongoose, { Schema, Document } from 'mongoose'

export interface IMessage extends Document {
  roomId: string
  senderId: string
  type: 'text' | 'image' | 'file' | 'voice' | 'system'
  content: string
  fileUrl?: string
  fileName?: string
  fileSize?: number
  replyTo?: string
  isDeleted: boolean
  readBy: string[]
  createdAt: Date
  updatedAt: Date
}

const MessageSchema: Schema = new Schema(
  {
    roomId: {
      type: String,
      required: true,
      index: true,
    },
    senderId: {
      type: String,
      required: true,
      index: true,
    },
    type: {
      type: String,
      enum: ['text', 'image', 'file', 'voice', 'system'],
      default: 'text',
    },
    content: {
      type: String,
      required: true,
    },
    fileUrl: String,
    fileName: String,
    fileSize: Number,
    replyTo: {
      type: Schema.Types.ObjectId,
      ref: 'Message',
    },
    isDeleted: {
      type: Boolean,
      default: false,
    },
    readBy: [
      {
        type: String,
      },
    ],
  },
  {
    timestamps: true,
  }
)

// 인덱스
MessageSchema.index({ roomId: 1, createdAt: -1 })
MessageSchema.index({ senderId: 1, createdAt: -1 })

export default mongoose.model<IMessage>('Message', MessageSchema)
