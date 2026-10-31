import http from './http'

/** 图片上传:已配置视觉模型时返回识别文本 */
export const uploadApi = {
  image(file) {
    const form = new FormData()
    form.append('file', file)
    return http.post('/uploads/image', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
  },
}
