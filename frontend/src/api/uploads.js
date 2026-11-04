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
  /** 多图上传:一次最多 3 张,返回 {items, vision_enabled} */
  images(files) {
    const form = new FormData()
    files.forEach((file) => form.append('files', file))
    return http.post('/uploads/images', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 180000,
    })
  },
  /** 录音转写:返回 {text},由用户确认后再发送 */
  audio(file) {
    const form = new FormData()
    form.append('file', file)
    return http.post('/uploads/audio', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
  },
  /** 本人识图图片:返回 {items, count} */
  listMine() {
    return http.get('/uploads/images/mine')
  },
  /** 删除本人识图图片 */
  removeMine(filename) {
    return http.delete(`/uploads/images/mine/${encodeURIComponent(filename)}`)
  },
}
