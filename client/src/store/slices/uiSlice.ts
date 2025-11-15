import { createSlice, PayloadAction } from '@reduxjs/toolkit'

interface UIState {
  isSidebarOpen: boolean
  isDarkMode: boolean
  activeRoomId: string | null
  isTyping: Record<string, string[]>
}

const initialState: UIState = {
  isSidebarOpen: true,
  isDarkMode: false,
  activeRoomId: null,
  isTyping: {},
}

const uiSlice = createSlice({
  name: 'ui',
  initialState,
  reducers: {
    toggleSidebar: (state) => {
      state.isSidebarOpen = !state.isSidebarOpen
    },
    setSidebarOpen: (state, action: PayloadAction<boolean>) => {
      state.isSidebarOpen = action.payload
    },
    setDarkMode: (state, action: PayloadAction<boolean>) => {
      state.isDarkMode = action.payload
      localStorage.setItem('darkMode', String(action.payload))
    },
    toggleDarkMode: (state) => {
      state.isDarkMode = !state.isDarkMode
      localStorage.setItem('darkMode', String(state.isDarkMode))
    },
    setActiveRoom: (state, action: PayloadAction<string | null>) => {
      state.activeRoomId = action.payload
    },
    setTyping: (
      state,
      action: PayloadAction<{ roomId: string; userId: string; isTyping: boolean }>
    ) => {
      const { roomId, userId, isTyping } = action.payload
      if (!state.isTyping[roomId]) {
        state.isTyping[roomId] = []
      }
      if (isTyping) {
        if (!state.isTyping[roomId].includes(userId)) {
          state.isTyping[roomId].push(userId)
        }
      } else {
        state.isTyping[roomId] = state.isTyping[roomId].filter(
          (id) => id !== userId
        )
      }
    },
  },
})

export const {
  toggleSidebar,
  setSidebarOpen,
  setDarkMode,
  toggleDarkMode,
  setActiveRoom,
  setTyping,
} = uiSlice.actions

export default uiSlice.reducer
