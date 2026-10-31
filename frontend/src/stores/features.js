import { reactive } from 'vue'
import { recordsApi } from '../api/records'

/** 全局能力开关:进入布局时拉取一次,供菜单/按钮灰度隐藏 */
export const features = reactive({
  loaded: false,
  feature_image_vision: true,
  feature_assignments: true,
  feature_course_share: true,
  feature_exams: true,
  upload_image_max_mb: 8,
  vision_daily_limit: 30,
})

export async function loadFeatures() {
  try {
    const data = await recordsApi.features()
    Object.assign(features, data)
  } catch {
    /* 读取失败按默认开启处理,由后端二次校验 */
  } finally {
    features.loaded = true
  }
}
