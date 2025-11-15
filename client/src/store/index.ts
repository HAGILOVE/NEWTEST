import { configureStore } from '@reduxjs/toolkit'
import authReducer from './slices/authSlice'
import uiReducer from './slices/uiSlice'
import chatReducer from './slices/chatSlice'

export const store = configureStore({
  reducer: {
    auth: authReducer,
    ui: uiReducer,
    chat: chatReducer,
  },
  middleware: (getDefaultMiddleware) =>
    getDefaultMiddleware({
      serializableCheck: {
        // Date 객체를 허용
        ignoredActions: ['chat/addMessage', 'chat/setMessages'],
        ignoredPaths: ['chat.messages'],
      },
    }),
})

export type RootState = ReturnType<typeof store.getState>
export type AppDispatch = typeof store.dispatch
