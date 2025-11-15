import { Request, Response, NextFunction } from 'express'

export const errorHandler = (
  err: any,
  req: Request,
  res: Response,
  next: NextFunction
) => {
  console.error('Error:', err)

  const status = err.status || 500
  const message = err.message || '서버 오류가 발생했습니다.'

  res.status(status).json({
    success: false,
    message,
    ...(process.env.NODE_ENV === 'development' && { stack: err.stack }),
  })
}

export const notFound = (req: Request, res: Response) => {
  res.status(404).json({
    success: false,
    message: '요청한 리소스를 찾을 수 없습니다.',
  })
}
