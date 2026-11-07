/** 考试答案判空与未答计数(手动交卷确认与页面答案保持同一口径) */

export function isAnswerEmpty(value) {
  if (Array.isArray(value)) return value.length === 0
  if (value === null || value === undefined) return true
  return String(value).trim() === ''
}

export function countUnanswered(questions = [], answers = {}) {
  return (questions || []).reduce(
    (count, question) => (
      isAnswerEmpty(answers?.[question.id]) ? count + 1 : count
    ),
    0,
  )
}
