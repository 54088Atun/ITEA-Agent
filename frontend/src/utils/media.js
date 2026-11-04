export function microphoneErrorMessage(error) {
  switch (error?.name) {
    case 'NotAllowedError':
      return '麦克风权限被拒绝，请在浏览器地址栏的网站设置中允许麦克风后重试'
    case 'NotFoundError':
      return '未检测到可用麦克风，请连接设备后重试'
    case 'NotReadableError':
      return '麦克风被其他应用占用或暂时不可用，请关闭占用应用后重试'
    default:
      return '无法访问麦克风，请检查浏览器权限和设备状态后重试'
  }
}
