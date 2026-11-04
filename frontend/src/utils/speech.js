import http from '../api/http.js'

let activePlayback = null

function releasePlayback(playback) {
  if (playback.audio) {
    playback.audio.onend = null
    playback.audio.onerror = null
  }
  if (playback.url) window.URL.revokeObjectURL(playback.url)
  playback.url = null
}

function cancelActive() {
  if (!activePlayback) return
  const playback = activePlayback
  activePlayback = null
  playback.controller.abort()
  playback.audio?.pause()
  releasePlayback(playback)
}

function settle(playback, callback, event) {
  if (activePlayback !== playback) return
  activePlayback = null
  releasePlayback(playback)
  callback?.(event)
}

export function isSpeechActive() {
  return activePlayback !== null
}

export function stopSpeech() {
  cancelActive()
}

export function isSpeechSupported() {
  return typeof window !== 'undefined'
    && typeof window.Audio === 'function'
    && typeof window.URL?.createObjectURL === 'function'
}

export async function speakMarkdown(markdown, { onEnd, onError } = {}) {
  if (!isSpeechSupported()) return false
  cancelActive()
  const playback = {
    controller: new AbortController(),
    audio: null,
    url: null,
  }
  activePlayback = playback

  try {
    const blob = await http.post('/speech', {
      text: markdownToPlainText(markdown),
    }, {
      responseType: 'blob',
      timeout: 120000,
      signal: playback.controller.signal,
    })
    if (activePlayback !== playback) return false

    playback.url = window.URL.createObjectURL(blob)
    playback.audio = new window.Audio(playback.url)
    playback.audio.onend = () => settle(playback, onEnd)
    playback.audio.onerror = event => settle(playback, onError, event)
    await playback.audio.play()
    return true
  } catch (error) {
    if (activePlayback !== playback) return false
    activePlayback = null
    releasePlayback(playback)
    onError?.(error)
    return false
  }
}

export function markdownToPlainText(markdown) {
  return String(markdown ?? '')
    .replace(/```[^\n]*(?:\n|$)/g, '')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/^\s*[-*+]\s+/gm, '')
    .replace(/!\[([^\]]*)\]\([^)]+\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/(\*\*|__)(.*?)\1/g, '$2')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .split('\n')
    .map(line => line.trim().replace(/[ \t]+/g, ' '))
    .filter(Boolean)
    .join('\n')
}
