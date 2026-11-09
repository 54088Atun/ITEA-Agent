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
  /** 教师目录检索:按姓名/邮箱搜索有效教师,用于选择课程协作教师 */
  searchTeachers({ keyword = '', courseId = null } = {}) {
    return http.get('/course/teachers', {
      params: { keyword, course_id: courseId || undefined },
    })
  },
  /** 课程协作教师列表 */
  collaborators(id) {
    return http.get(`/course/${id}/collaborators`)
  },
  addCollaborator(id, teacherId) {
    return http.post(`/course/${id}/collaborators`, { teacher_id: teacherId })
  },
  removeCollaborator(id, teacherId) {
    return http.delete(`/course/${id}/collaborators/${teacherId}`)
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
  /** 素材原文地址(同源 Cookie 鉴权,可直接给 iframe/img 使用) */
  materialPreviewUrl(id, materialId) {
    return `/api/course/${id}/materials/${materialId}/preview`
  },
  /** 带鉴权获取预览内容;Office 文档传 render='pdf' 由服务端转 PDF */
  materialPreviewBlob(id, materialId, { render = '', silent = false } = {}) {
    return http.get(`/course/${id}/materials/${materialId}/preview`, {
      params: render ? { render } : {},
      responseType: 'blob',
      timeout: 180000,
      silent,
    })
  },
  /** 带鉴权下载素材 */
  materialDownloadBlob(id, materialId) {
    return http.get(`/course/${id}/materials/${materialId}/download`, {
      responseType: 'blob',
      timeout: 180000,
    })
  },
  /** 解析文本:Office/压缩包等无法直接渲染的文件用它做文字预览 */
  materialText(id, materialId) {
    return http.get(`/course/${id}/materials/${materialId}/text`)
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
  /** 修改课件标题/类型(课程创建者或管理员) */
  updateMaterial(id, materialId, data) {
    return http.patch(`/course/${id}/materials/${materialId}`, data)
  },
  /** 删除课件(课程创建者或管理员),同步清理文件与检索索引 */
  deleteMaterial(id, materialId) {
    return http.delete(`/course/${id}/materials/${materialId}`)
  },
}
