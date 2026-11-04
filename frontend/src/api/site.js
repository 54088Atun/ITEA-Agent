import http from './http'

/** 公开站点内容(首页 / 联系页) */
export const siteApi = {
  content() {
    return http.get('/site/content')
  },
}
