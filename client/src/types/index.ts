// 사용자 타입
export interface User {
  id: string;
  email: string;
  username: string;
  phone?: string;
  profileImage?: string;
  statusMessage?: string;
  isOnline: boolean;
  lastSeen?: Date;
  createdAt: Date;
}

// 친구 타입
export interface Friend extends User {
  isFavorite: boolean;
  friendshipId: string;
}

// 메시지 타입
export type MessageType = 'text' | 'image' | 'file' | 'voice' | 'system';

export interface Message {
  id: string;
  roomId: string;
  senderId: string;
  sender?: User;
  type: MessageType;
  content: string;
  fileUrl?: string;
  fileName?: string;
  fileSize?: number;
  replyTo?: Message;
  isDeleted: boolean;
  readBy: string[];
  createdAt: Date;
}

// 채팅방 타입
export type RoomType = 'direct' | 'group';

export interface ChatRoom {
  id: string;
  name?: string;
  type: RoomType;
  profileImage?: string;
  members: User[];
  lastMessage?: Message;
  unreadCount: number;
  createdBy: string;
  createdAt: Date;
  updatedAt: Date;
}

export interface ChatRoomMember {
  id: string;
  roomId: string;
  userId: string;
  user?: User;
  role: 'admin' | 'member';
  joinedAt: Date;
  lastReadAt?: Date;
}

// 인증 관련 타입
export interface LoginCredentials {
  email: string;
  password: string;
}

export interface RegisterData {
  email: string;
  username: string;
  password: string;
  phone?: string;
}

export interface AuthResponse {
  user: User;
  accessToken: string;
  refreshToken: string;
}

// API 응답 타입
export interface ApiResponse<T> {
  success: boolean;
  data?: T;
  message?: string;
  error?: string;
}

export interface PaginatedResponse<T> {
  data: T[];
  total: number;
  page: number;
  limit: number;
  hasMore: boolean;
}

// WebSocket 이벤트 타입
export interface TypingEvent {
  roomId: string;
  userId: string;
  username: string;
  isTyping: boolean;
}

export interface OnlineStatusEvent {
  userId: string;
  isOnline: boolean;
  lastSeen?: Date;
}

export interface MessageReadEvent {
  messageId: string;
  roomId: string;
  userId: string;
  readAt: Date;
}

// UI 상태 타입
export interface UIState {
  isSidebarOpen: boolean;
  isDarkMode: boolean;
  activeRoomId: string | null;
  isTyping: Record<string, string[]>; // roomId -> userIds
}

// 알림 타입
export interface Notification {
  id: string;
  type: 'message' | 'friend_request' | 'system';
  title: string;
  body: string;
  data?: any;
  isRead: boolean;
  createdAt: Date;
}
