import http from './http'

/** 知识点/素材接口均为 FormData 提交,字段与后端 Form(...) 对齐 */
export const courseApi = {
  /** 课程列表 → 直接返回数组(后端 List[CourseOut]) */
  list() {
    return http.get('/course/list')
  },
  create(data) {
    // {name, code, syllabus, semester}
    return http.post('/course/create', data)
  },
  detail(id) {
    return http.get(`/course/${id}`)
  },
  /** 知识点列表 → [{id, name, description, parent_id}] */
  knowledgePoints(id) {
    return http.get(`/course/${id}/knowledge-points`)
  },
  addKnowledgePoint(id, { name, description = '', parentId = null }) {
    const form = new FormData()
    form.append('name', name)
    form.append('description', description)
    if (parentId !== null && parentId !== undefined && parentId !== '') {
      form.append('parent_id', parentId)
    }
    return http.post(`/course/${id}/knowledge-points`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  /** 素材列表 → [{id, ..., parse_status, parse_progress, parse_error}] */
  materials(id) {
    return http.get(`/course/${id}/materials`)
  },
  /** 重新解析/复核(解析失败或内容审核未通过时) */
  retryMaterialParse(id, materialId) {
    return http.post(`/course/${id}/materials/${materialId}/parse/retry`)
  },
  uploadMaterial(id, type, title, file) {
    const form = new FormData()
    form.append('type', type)
    form.append('title', title)
    form.append('file', file)
    return http.post(`/course/${id}/materials`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
  },
}
