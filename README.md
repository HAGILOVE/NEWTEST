# KakaoChat - 실시간 메신저 애플리케이션

카카오톡 스타일의 전문적인 실시간 채팅 애플리케이션입니다. React, Node.js, WebSocket을 활용하여 구축되었습니다.

## 📋 목차

- [주요 기능](#주요-기능)
- [기술 스택](#기술-스택)
- [시작하기](#시작하기)
- [프로젝트 구조](#프로젝트-구조)
- [API 문서](#api-문서)
- [배포](#배포)

## ✨ 주요 기능

### 사용자 관리
- ✅ 이메일/전화번호 기반 회원가입
- ✅ JWT 토큰 기반 인증
- ✅ 프로필 관리 (사진, 상태 메시지)
- ✅ 온라인/오프라인 상태 표시

### 친구 관리
- ✅ 친구 추가/삭제
- ✅ 친구 검색
- ✅ 즐겨찾기 기능
- ✅ 친구 온라인 상태 실시간 업데이트

### 채팅 기능
- ✅ 1:1 채팅
- ✅ 그룹 채팅 (최대 500명)
- ✅ 실시간 메시지 송수신
- ✅ 타이핑 표시
- ✅ 읽음 표시 (Read Receipts)
- ✅ 메시지 삭제
- ✅ 이미지/파일 전송
- ✅ 메시지 검색

### UI/UX
- ✅ 카카오톡 스타일 디자인
- ✅ 다크 모드 지원
- ✅ 반응형 레이아웃
- ✅ 부드러운 애니메이션

## 🛠 기술 스택

### Frontend
- **React 18** - UI 라이브러리
- **TypeScript** - 타입 안정성
- **Redux Toolkit** - 상태 관리
- **Socket.IO Client** - 실시간 통신
- **Tailwind CSS** - 스타일링
- **React Router v6** - 라우팅
- **Axios** - HTTP 클라이언트
- **Vite** - 빌드 도구

### Backend
- **Node.js** - 런타임
- **Express.js** - 웹 프레임워크
- **TypeScript** - 타입 안정성
- **Socket.IO** - WebSocket 서버
- **PostgreSQL** - 관계형 데이터베이스
- **MongoDB** - NoSQL 데이터베이스 (메시지)
- **Redis** - 캐싱 및 세션
- **Prisma ORM** - PostgreSQL ORM
- **Mongoose** - MongoDB ODM
- **JWT** - 인증/인가
- **Multer** - 파일 업로드
- **Sharp** - 이미지 처리

### DevOps
- **Docker** - 컨테이너화
- **Docker Compose** - 멀티 컨테이너 관리
- **Nginx** - 리버스 프록시

## 🚀 시작하기

### 필수 요구사항

- Node.js 20+
- Docker & Docker Compose (선택사항)
- PostgreSQL 16+
- MongoDB 7+
- Redis 7+

### 로컬 개발 환경 설정

#### 1. 저장소 클론

```bash
git clone <repository-url>
cd NEWTEST
```

#### 2. 환경 변수 설정

**서버 환경 변수**
```bash
cd server
cp .env.example .env
# .env 파일을 편집하여 데이터베이스 설정 등을 구성
```

**클라이언트 환경 변수**
```bash
cd client
cp .env.example .env
# .env 파일을 편집하여 API URL 설정
```

#### 3. 의존성 설치

**서버**
```bash
cd server
npm install
```

**클라이언트**
```bash
cd client
npm install
```

#### 4. 데이터베이스 설정

**Prisma 마이그레이션 실행**
```bash
cd server
npx prisma generate
npx prisma migrate dev
```

#### 5. 개발 서버 실행

**서버 실행 (터미널 1)**
```bash
cd server
npm run dev
```

**클라이언트 실행 (터미널 2)**
```bash
cd client
npm run dev
```

서버: http://localhost:5000
클라이언트: http://localhost:3000

### Docker를 사용한 실행

```bash
# 모든 서비스 실행
docker-compose up -d

# 로그 확인
docker-compose logs -f

# 서비스 중지
docker-compose down
```

## 📁 프로젝트 구조

```
NEWTEST/
├── client/                 # 프론트엔드
│   ├── src/
│   │   ├── components/     # React 컴포넌트
│   │   ├── pages/          # 페이지 컴포넌트
│   │   ├── store/          # Redux 스토어
│   │   ├── services/       # API 및 Socket 서비스
│   │   ├── hooks/          # 커스텀 훅
│   │   ├── types/          # TypeScript 타입
│   │   └── utils/          # 유틸리티 함수
│   ├── public/
│   └── package.json
│
├── server/                 # 백엔드
│   ├── src/
│   │   ├── controllers/    # 요청 핸들러
│   │   ├── routes/         # API 라우트
│   │   ├── models/         # MongoDB 모델
│   │   ├── middleware/     # 미들웨어
│   │   ├── socket/         # Socket.IO 핸들러
│   │   ├── config/         # 설정 파일
│   │   ├── types/          # TypeScript 타입
│   │   └── utils/          # 유틸리티 함수
│   ├── prisma/             # Prisma 스키마
│   ├── uploads/            # 업로드된 파일
│   └── package.json
│
├── docker-compose.yml      # Docker Compose 설정
├── ARCHITECTURE.md         # 아키텍처 문서
└── README.md
```

## 📝 라이선스

MIT License

## 📧 문의

프로젝트에 대한 문의사항이 있으시면 이슈를 생성해주세요.
