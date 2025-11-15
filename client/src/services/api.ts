import axios, { AxiosInstance, AxiosError } from 'axios'
import toast from 'react-hot-toast'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000/api'

class ApiService {
  private api: AxiosInstance

  constructor() {
    this.api = axios.create({
      baseURL: API_URL,
      headers: {
        'Content-Type': 'application/json',
      },
    })

    // 요청 인터셉터
    this.api.interceptors.request.use(
      (config) => {
        const token = localStorage.getItem('accessToken')
        if (token) {
          config.headers.Authorization = `Bearer ${token}`
        }
        return config
      },
      (error) => {
        return Promise.reject(error)
      }
    )

    // 응답 인터셉터
    this.api.interceptors.response.use(
      (response) => response,
      async (error: AxiosError<any>) => {
        const originalRequest = error.config as any

        // 토큰 만료시 재발급 시도
        if (error.response?.status === 401 && !originalRequest._retry) {
          originalRequest._retry = true

          try {
            const refreshToken = localStorage.getItem('refreshToken')
            const response = await axios.post(`${API_URL}/auth/refresh`, {
              refreshToken,
            })

            const { accessToken } = response.data
            localStorage.setItem('accessToken', accessToken)

            originalRequest.headers.Authorization = `Bearer ${accessToken}`
            return this.api(originalRequest)
          } catch (refreshError) {
            localStorage.removeItem('accessToken')
            localStorage.removeItem('refreshToken')
            window.location.href = '/login'
            return Promise.reject(refreshError)
          }
        }

        // 에러 메시지 표시
        const message = error.response?.data?.message || '오류가 발생했습니다.'
        toast.error(message)

        return Promise.reject(error)
      }
    )
  }

  // Auth APIs
  async login(email: string, password: string) {
    const response = await this.api.post('/auth/login', { email, password })
    return response.data
  }

  async register(data: {
    email: string
    username: string
    password: string
    phone?: string
  }) {
    const response = await this.api.post('/auth/register', data)
    return response.data
  }

  async logout() {
    const response = await this.api.post('/auth/logout')
    return response.data
  }

  async getCurrentUser() {
    const response = await this.api.get('/users/me')
    return response.data
  }

  // User APIs
  async updateProfile(data: {
    username?: string
    statusMessage?: string
    profileImage?: string
  }) {
    const response = await this.api.put('/users/me', data)
    return response.data
  }

  async uploadAvatar(file: File) {
    const formData = new FormData()
    formData.append('avatar', file)
    const response = await this.api.post('/upload/avatar', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
    return response.data
  }

  async searchUsers(query: string) {
    const response = await this.api.get('/users/search', { params: { q: query } })
    return response.data
  }

  // Friend APIs
  async getFriends() {
    const response = await this.api.get('/friends')
    return response.data
  }

  async addFriend(userId: string) {
    const response = await this.api.post('/friends', { userId })
    return response.data
  }

  async removeFriend(friendshipId: string) {
    const response = await this.api.delete(`/friends/${friendshipId}`)
    return response.data
  }

  async toggleFavorite(friendshipId: string) {
    const response = await this.api.put(`/friends/${friendshipId}/favorite`)
    return response.data
  }

  // Chat Room APIs
  async getRooms() {
    const response = await this.api.get('/rooms')
    return response.data
  }

  async getRoom(roomId: string) {
    const response = await this.api.get(`/rooms/${roomId}`)
    return response.data
  }

  async createRoom(data: {
    name?: string
    type: 'direct' | 'group'
    memberIds: string[]
  }) {
    const response = await this.api.post('/rooms', data)
    return response.data
  }

  async updateRoom(roomId: string, data: { name?: string }) {
    const response = await this.api.put(`/rooms/${roomId}`, data)
    return response.data
  }

  async leaveRoom(roomId: string) {
    const response = await this.api.delete(`/rooms/${roomId}/leave`)
    return response.data
  }

  async inviteToRoom(roomId: string, userIds: string[]) {
    const response = await this.api.post(`/rooms/${roomId}/invite`, { userIds })
    return response.data
  }

  // Message APIs
  async getMessages(roomId: string, page = 1, limit = 50) {
    const response = await this.api.get(`/messages/${roomId}`, {
      params: { page, limit },
    })
    return response.data
  }

  async sendMessage(data: {
    roomId: string
    content: string
    type?: 'text' | 'image' | 'file'
    replyToId?: string
  }) {
    const response = await this.api.post('/messages', data)
    return response.data
  }

  async deleteMessage(messageId: string) {
    const response = await this.api.delete(`/messages/${messageId}`)
    return response.data
  }

  async uploadFile(roomId: string, file: File) {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('roomId', roomId)
    const response = await this.api.post('/upload/file', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
    return response.data
  }
}

export default new ApiService()
