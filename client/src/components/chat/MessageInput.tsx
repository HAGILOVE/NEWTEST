import { useState, useRef, useEffect } from 'react'
import { FiSend, FiPaperclip, FiImage, FiSmile } from 'react-icons/fi'
import socketService from '@services/socket'
import api from '@services/api'
import toast from 'react-hot-toast'

interface MessageInputProps {
  roomId: string
}

export default function MessageInput({ roomId }: MessageInputProps) {
  const [message, setMessage] = useState('')
  const [isSending, setIsSending] = useState(false)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const typingTimeoutRef = useRef<NodeJS.Timeout>()

  useEffect(() => {
    return () => {
      if (typingTimeoutRef.current) {
        clearTimeout(typingTimeoutRef.current)
        socketService.stopTyping(roomId)
      }
    }
  }, [roomId])

  const handleTyping = () => {
    socketService.startTyping(roomId)

    if (typingTimeoutRef.current) {
      clearTimeout(typingTimeoutRef.current)
    }

    typingTimeoutRef.current = setTimeout(() => {
      socketService.stopTyping(roomId)
    }, 1000)
  }

  const handleSend = async () => {
    if (!message.trim() || isSending) return

    setIsSending(true)
    const messageContent = message.trim()
    setMessage('')

    try {
      socketService.stopTyping(roomId)
      await api.sendMessage({
        roomId,
        content: messageContent,
        type: 'text',
      })

      // 포커스 유지
      inputRef.current?.focus()
    } catch (error) {
      console.error('Failed to send message:', error)
      setMessage(messageContent)
    } finally {
      setIsSending(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    // 파일 크기 제한 (100MB)
    if (file.size > 100 * 1024 * 1024) {
      toast.error('파일 크기는 100MB를 초과할 수 없습니다.')
      return
    }

    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('roomId', roomId)

      await api.uploadFile(roomId, file)
      toast.success('파일을 전송했습니다.')
    } catch (error) {
      console.error('Failed to upload file:', error)
    }

    // 입력 초기화
    e.target.value = ''
  }

  return (
    <div className="bg-white dark:bg-gray-800 border-t border-gray-200 dark:border-gray-700 p-4">
      <div className="flex items-end space-x-2">
        <div className="flex space-x-1">
          <input
            type="file"
            id="file-upload"
            className="hidden"
            onChange={handleFileUpload}
          />
          <label
            htmlFor="file-upload"
            className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 cursor-pointer transition-colors"
            title="파일 첨부"
          >
            <FiPaperclip className="w-5 h-5 text-gray-600 dark:text-gray-400" />
          </label>

          <input
            type="file"
            id="image-upload"
            className="hidden"
            accept="image/*"
            onChange={handleFileUpload}
          />
          <label
            htmlFor="image-upload"
            className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 cursor-pointer transition-colors"
            title="이미지 첨부"
          >
            <FiImage className="w-5 h-5 text-gray-600 dark:text-gray-400" />
          </label>

          <button
            className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
            title="이모티콘"
          >
            <FiSmile className="w-5 h-5 text-gray-600 dark:text-gray-400" />
          </button>
        </div>

        <div className="flex-1 relative">
          <textarea
            ref={inputRef}
            value={message}
            onChange={(e) => {
              setMessage(e.target.value)
              handleTyping()
            }}
            onKeyDown={handleKeyDown}
            placeholder="메시지를 입력하세요..."
            className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 dark:bg-gray-700 dark:text-white resize-none"
            rows={1}
            style={{
              minHeight: '40px',
              maxHeight: '120px',
            }}
            onInput={(e) => {
              const target = e.target as HTMLTextAreaElement
              target.style.height = 'auto'
              target.style.height = target.scrollHeight + 'px'
            }}
          />
        </div>

        <button
          onClick={handleSend}
          disabled={!message.trim() || isSending}
          className="p-3 bg-kakao-yellow text-kakao-brown rounded-lg hover:bg-yellow-400 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          title="전송"
        >
          <FiSend className="w-5 h-5" />
        </button>
      </div>
    </div>
  )
}
