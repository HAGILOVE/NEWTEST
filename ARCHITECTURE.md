# 카카오톡 스타일 채팅 애플리케이션 - 아키텍처 설계

## 1. 프로젝트 개요
전문적인 상용 수준의 실시간 채팅 애플리케이션으로, 카카오톡의 핵심 기능을 모두 구현합니다.

## 2. 기술 스택

### Frontend
- **React 18** with TypeScript
- **Redux Toolkit** - 상태 관리
- **Socket.IO Client** - 실시간 통신
- **Tailwind CSS** - 스타일링
- **React Router v6** - 라우팅
- **Axios** - HTTP 클라이언트
- **React Query** - 서버 상태 관리
- **Zustand** - 경량 상태 관리 (UI 상태)

### Backend
- **Node.js** with TypeScript
- **Express.js** - REST API
- **Socket.IO** - WebSocket 실시간 통신
- **PostgreSQL** - 주 데이터베이스 (사용자, 채팅방)
- **MongoDB** - 메시지 저장 (확장성)
- **Redis** - 캐싱 및 세션 관리
- **JWT** - 인증/인가
- **Prisma ORM** - PostgreSQL ORM
- **Mongoose** - MongoDB ODM
- **Multer** - 파일 업로드
- **Sharp** - 이미지 처리

### DevOps & Infrastructure
- **Docker** - 컨테이너화
- **Nginx** - 리버스 프록시
- **AWS S3** - 파일 저장소
- **PM2** - 프로세스 관리

## 3. 시스템 아키텍처

```
┌─────────────────────────────────────────────┐
│           Frontend (React)                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │  Login   │  │  Chat    │  │ Friends  │  │
│  └──────────┘  └──────────┘  └──────────┘  │
└─────────────────────────────────────────────┘
           │              │
           │ HTTP/WSS     │
           ▼              ▼
┌─────────────────────────────────────────────┐
│            Backend Services                 │
│  ┌──────────────────────────────────────┐  │
│  │     Express REST API Server           │  │
│  └──────────────────────────────────────┘  │
│  ┌──────────────────────────────────────┐  │
│  │     Socket.IO WebSocket Server        │  │
│  └──────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
           │              │              │
           ▼              ▼              ▼
    ┌──────────┐   ┌──────────┐   ┌──────────┐
    │PostgreSQL│   │ MongoDB  │   │  Redis   │
    │(Users,   │   │(Messages)│   │(Sessions)│
    │ Rooms)   │   │          │   │          │
    └──────────┘   └──────────┘   └──────────┘
```

## 4. 핵심 기능 목록

### 4.1 사용자 관리
- [x] 회원가입 (이메일, 전화번호)
- [x] 로그인/로그아웃
- [x] JWT 기반 인증
- [x] 프로필 관리 (사진, 상태 메시지)
- [x] 비밀번호 재설정

### 4.2 친구 관리
- [x] 친구 추가 (ID 검색, QR 코드)
- [x] 친구 목록 조회
- [x] 친구 삭제
- [x] 즐겨찾기
- [x] 친구 차단

### 4.3 채팅 기능
- [x] 1:1 채팅
- [x] 그룹 채팅 (최대 500명)
- [x] 텍스트 메시지
- [x] 이미지 전송
- [x] 파일 전송 (최대 100MB)
- [x] 음성 메시지
- [x] 이모티콘
- [x] 답장 기능
- [x] 메시지 삭제

### 4.4 실시간 기능
- [x] 실시간 메시지 수신
- [x] 타이핑 표시
- [x] 읽음 표시 (Read Receipts)
- [x] 온라인/오프라인 상태
- [x] 마지막 접속 시간

### 4.5 채팅방 관리
- [x] 채팅방 목록
- [x] 안 읽은 메시지 카운트
- [x] 채팅방 나가기
- [x] 채팅방 설정 (알림 on/off)
- [x] 채팅방 검색
- [x] 메시지 검색

### 4.6 알림
- [x] 푸시 알림
- [x] 데스크톱 알림
- [x] 알림 설정 (채팅방별)

### 4.7 추가 기능
- [x] 다크 모드
- [x] 메시지 암호화 (E2E)
- [x] 채팅 백업
- [x] 멀티 디바이스 지원

## 5. 데이터베이스 스키마

### PostgreSQL (관계형 데이터)

#### Users
```sql
- id: UUID (PK)
- email: VARCHAR(255) UNIQUE
- phone: VARCHAR(20) UNIQUE
- password: VARCHAR(255) (hashed)
- username: VARCHAR(50)
- profileImage: VARCHAR(500)
- statusMessage: TEXT
- createdAt: TIMESTAMP
- updatedAt: TIMESTAMP
```

#### Friends
```sql
- id: UUID (PK)
- userId: UUID (FK -> Users)
- friendId: UUID (FK -> Users)
- isFavorite: BOOLEAN
- createdAt: TIMESTAMP
```

#### ChatRooms
```sql
- id: UUID (PK)
- name: VARCHAR(100)
- type: ENUM('direct', 'group')
- createdBy: UUID (FK -> Users)
- createdAt: TIMESTAMP
- updatedAt: TIMESTAMP
```

#### ChatRoomMembers
```sql
- id: UUID (PK)
- roomId: UUID (FK -> ChatRooms)
- userId: UUID (FK -> Users)
- role: ENUM('admin', 'member')
- joinedAt: TIMESTAMP
- lastReadAt: TIMESTAMP
```

### MongoDB (메시지 데이터)

#### Messages
```json
{
  "_id": "ObjectId",
  "roomId": "UUID",
  "senderId": "UUID",
  "type": "text|image|file|voice",
  "content": "String",
  "fileUrl": "String",
  "fileName": "String",
  "fileSize": "Number",
  "replyTo": "ObjectId",
  "isDeleted": "Boolean",
  "createdAt": "Date",
  "readBy": ["UUID"]
}
```

## 6. API 엔드포인트

### 인증
- POST /api/auth/register - 회원가입
- POST /api/auth/login - 로그인
- POST /api/auth/logout - 로그아웃
- POST /api/auth/refresh - 토큰 갱신

### 사용자
- GET /api/users/me - 내 프로필 조회
- PUT /api/users/me - 프로필 수정
- GET /api/users/:id - 사용자 조회
- POST /api/users/upload-avatar - 프로필 사진 업로드

### 친구
- GET /api/friends - 친구 목록
- POST /api/friends - 친구 추가
- DELETE /api/friends/:id - 친구 삭제
- PUT /api/friends/:id/favorite - 즐겨찾기 토글

### 채팅방
- GET /api/rooms - 채팅방 목록
- POST /api/rooms - 채팅방 생성
- GET /api/rooms/:id - 채팅방 조회
- PUT /api/rooms/:id - 채팅방 수정
- DELETE /api/rooms/:id/leave - 채팅방 나가기
- POST /api/rooms/:id/invite - 멤버 초대

### 메시지
- GET /api/messages/:roomId - 메시지 조회 (페이지네이션)
- POST /api/messages - 메시지 전송
- DELETE /api/messages/:id - 메시지 삭제
- POST /api/messages/upload - 파일 업로드

## 7. WebSocket 이벤트

### Client → Server
- `join_room` - 채팅방 입장
- `leave_room` - 채팅방 퇴장
- `send_message` - 메시지 전송
- `typing_start` - 타이핑 시작
- `typing_stop` - 타이핑 종료
- `mark_read` - 메시지 읽음 처리

### Server → Client
- `new_message` - 새 메시지 수신
- `message_deleted` - 메시지 삭제됨
- `user_typing` - 사용자 타이핑 중
- `message_read` - 메시지 읽음
- `user_online` - 사용자 온라인
- `user_offline` - 사용자 오프라인

## 8. 보안 고려사항

- JWT 토큰 기반 인증 (Access Token + Refresh Token)
- 비밀번호 bcrypt 해싱
- HTTPS 통신
- XSS 방지
- CSRF 토큰
- Rate Limiting
- 파일 업로드 검증
- SQL Injection 방지 (Prisma ORM)
- WebSocket 연결 인증

## 9. 성능 최적화

- Redis 캐싱 (사용자 세션, 온라인 상태)
- 메시지 페이지네이션
- 이미지 리사이징 및 압축
- CDN 사용 (정적 파일)
- Connection Pooling
- 인덱싱 전략
- Lazy Loading
- Virtual Scrolling (긴 채팅 목록)

## 10. 개발 단계

### Phase 1: 기본 인프라 (1-2주)
- 프로젝트 구조 설정
- 데이터베이스 설정
- 인증 시스템

### Phase 2: 핵심 채팅 기능 (2-3주)
- 실시간 메시지
- 채팅방 관리
- 파일 업로드

### Phase 3: 소셜 기능 (1-2주)
- 친구 관리
- 프로필 관리

### Phase 4: 고급 기능 (2-3주)
- 읽음 표시
- 타이핑 표시
- 알림 시스템

### Phase 5: UI/UX 완성 (1-2주)
- 디자인 시스템
- 반응형 레이아웃
- 애니메이션

## 11. 테스트 전략

- Unit Tests (Jest)
- Integration Tests (Supertest)
- E2E Tests (Cypress)
- Load Testing (Artillery)

## 12. 배포 전략

- Docker 컨테이너화
- CI/CD 파이프라인
- 무중단 배포
- 모니터링 (Prometheus, Grafana)
- 로깅 (Winston, ELK Stack)
