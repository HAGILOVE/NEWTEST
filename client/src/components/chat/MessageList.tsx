import { useEffect, useRef } from 'react'
import { useAppSelector } from '@hooks/redux'
import { format, isToday, isYesterday } from 'date-fns'
import { ko } from 'date-fns/locale'
import { Message } from '@types/index'

interface MessageListProps {
  messages: Message[]
  roomId: string
}

export default function MessageList({ messages, roomId }: MessageListProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const { user } = useAppSelector((state) => state.auth)
  const { isTyping } = useAppSelector((state) => state.ui)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const formatMessageTime = (date: Date) => {
    return format(new Date(date), 'a h:mm', { locale: ko })
  }

  const formatDateSeparator = (date: Date) => {
    const messageDate = new Date(date)
    if (isToday(messageDate)) {
      return '오늘'
    }
    if (isYesterday(messageDate)) {
      return '어제'
    }
    return format(messageDate, 'yyyy년 M월 d일', { locale: ko })
  }

  const shouldShowDateSeparator = (currentMsg: Message, prevMsg?: Message) => {
    if (!prevMsg) return true
    const currentDate = new Date(currentMsg.createdAt).toDateString()
    const prevDate = new Date(prevMsg.createdAt).toDateString()
    return currentDate !== prevDate
  }

  const isSentByMe = (message: Message) => {
    return message.senderId === user?.id
  }

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="text-center">
          <p className="text-gray-500 dark:text-gray-400">
            메시지가 없습니다
          </p>
          <p className="text-sm text-gray-400 dark:text-gray-500 mt-2">
            첫 메시지를 보내보세요!
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto scrollbar-thin p-4 space-y-4">
      {messages.map((message, index) => {
        const showDate = shouldShowDateSeparator(message, messages[index - 1])
        const sentByMe = isSentByMe(message)

        return (
          <div key={message.id}>
            {showDate && (
              <div className="flex justify-center my-4">
                <div className="bg-gray-200 dark:bg-gray-700 px-4 py-1 rounded-full text-xs text-gray-600 dark:text-gray-400">
                  {formatDateSeparator(message.createdAt)}
                </div>
              </div>
            )}

            <div
              className={`flex ${sentByMe ? 'justify-end' : 'justify-start'}`}
            >
              <div
                className={`flex ${
                  sentByMe ? 'flex-row-reverse' : 'flex-row'
                } items-end space-x-2 max-w-[70%]`}
              >
                {!sentByMe && (
                  <div className="flex-shrink-0">
                    {message.sender?.profileImage ? (
                      <img
                        src={message.sender.profileImage}
                        alt={message.sender.username}
                        className="avatar-sm"
                      />
                    ) : (
                      <div className="avatar-sm bg-gray-400 flex items-center justify-center text-white text-xs font-semibold">
                        {message.sender?.username.charAt(0).toUpperCase()}
                      </div>
                    )}
                  </div>
                )}

                <div className={sentByMe ? 'ml-2' : 'mr-2'}>
                  {!sentByMe && message.sender && (
                    <p className="text-xs text-gray-600 dark:text-gray-400 mb-1 ml-1">
                      {message.sender.username}
                    </p>
                  )}

                  <div
                    className={`flex items-end ${
                      sentByMe ? 'flex-row-reverse' : 'flex-row'
                    } space-x-2`}
                  >
                    <div
                      className={
                        sentByMe
                          ? 'message-bubble-sent'
                          : 'message-bubble-received'
                      }
                    >
                      {message.isDeleted ? (
                        <p className="text-sm italic opacity-50">
                          {message.content}
                        </p>
                      ) : message.type === 'text' ? (
                        <p className="text-sm whitespace-pre-wrap break-words">
                          {message.content}
                        </p>
                      ) : message.type === 'image' ? (
                        <div>
                          <img
                            src={message.fileUrl}
                            alt="Image"
                            className="max-w-full rounded-lg"
                          />
                        </div>
                      ) : (
                        <div className="flex items-center space-x-2">
                          <svg
                            className="w-5 h-5"
                            fill="currentColor"
                            viewBox="0 0 20 20"
                          >
                            <path
                              fillRule="evenodd"
                              d="M8 4a3 3 0 00-3 3v4a5 5 0 0010 0V7a1 1 0 112 0v4a7 7 0 11-14 0V7a5 5 0 0110 0v4a3 3 0 11-6 0V7a1 1 0 012 0v4a1 1 0 102 0V7a3 3 0 00-3-3z"
                              clipRule="evenodd"
                            />
                          </svg>
                          <span className="text-sm">{message.fileName}</span>
                        </div>
                      )}
                    </div>

                    <div className="flex flex-col items-center justify-end">
                      <span
                        className={`text-xs text-gray-500 dark:text-gray-400 ${
                          sentByMe ? 'mr-1' : 'ml-1'
                        }`}
                      >
                        {formatMessageTime(message.createdAt)}
                      </span>
                      {sentByMe && message.readBy && message.readBy.length > 1 && (
                        <span className="text-xs text-primary-500 mr-1">
                          읽음
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )
      })}

      {isTyping[roomId] && isTyping[roomId].length > 0 && (
        <div className="flex justify-start">
          <div className="message-bubble-received">
            <div className="flex space-x-1">
              <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce"></div>
              <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce delay-100"></div>
              <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce delay-200"></div>
            </div>
          </div>
        </div>
      )}

      <div ref={messagesEndRef} />
    </div>
  )
}
