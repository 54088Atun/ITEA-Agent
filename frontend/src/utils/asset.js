/**
 * 统一解析静态资源路径。
 * 后端返回的图片地址多为根路径（如 /static/site/xxx.png），
 * 当应用部署在子路径（BASE_URL 非 /）时需补上前缀；外链与 data/blob 原样返回。
 */
const BASE = import.meta.env.BASE_URL || '/'

export function resolveAsset(path) {
  if (!path) return ''
  const value = String(path)
  if (/^(https?:)?\/\//.test(value) || value.startsWith('data:') || value.startsWith('blob:')) {
    return value
  }
  const prefix = BASE.endsWith('/') ? BASE.slice(0, -1) : BASE
  if (prefix && value.startsWith(`${prefix}/`)) return value
  return `${prefix}/${value.replace(/^\//, '')}`
}
