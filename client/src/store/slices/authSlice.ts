import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import { User } from '@types/index'

interface AuthState {
  user: User | null
  accessToken: string | null
  isAuthenticated: boolean
  isLoading: boolean
}

const initialState: AuthState = {
  user: null,
  accessToken: localStorage.getItem('accessToken'),
  isAuthenticated: !!localStorage.getItem('accessToken'),
  isLoading: true,
}

const authSlice = createSlice({
  name: 'auth',
  initialState,
  reducers: {
    setCredentials: (
      state,
      action: PayloadAction<{ user: User; accessToken: string }>
    ) => {
      state.user = action.payload.user
      state.accessToken = action.payload.accessToken
      state.isAuthenticated = true
      state.isLoading = false
      localStorage.setItem('accessToken', action.payload.accessToken)
    },
    setUser: (state, action: PayloadAction<User>) => {
      state.user = action.payload
      state.isLoading = false
    },
    logout: (state) => {
      state.user = null
      state.accessToken = null
      state.isAuthenticated = false
      state.isLoading = false
      localStorage.removeItem('accessToken')
    },
    setLoading: (state, action: PayloadAction<boolean>) => {
      state.isLoading = action.payload
    },
  },
})

export const { setCredentials, setUser, logout, setLoading } = authSlice.actions
export default authSlice.reducer
