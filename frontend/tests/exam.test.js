import test from 'node:test'
import assert from 'node:assert/strict'

import { isAnswerEmpty, countUnanswered } from '../src/utils/exam.js'

const QUESTIONS = [
  { id: 1, type: 'single' },
  { id: 2, type: 'multiple' },
  { id: 3, type: 'judge' },
  { id: 4, type: 'short' },
]

test('空数组、空字符串、缺失答案均计入未答', () => {
  assert.equal(isAnswerEmpty([]), true)
  assert.equal(isAnswerEmpty(''), true)
  assert.equal(isAnswerEmpty('   '), true)
  assert.equal(isAnswerEmpty(null), true)
  assert.equal(isAnswerEmpty(undefined), true)
  assert.equal(isAnswerEmpty('A'), false)
  assert.equal(isAnswerEmpty(['A']), false)
})

test('各题型混合时未答数量准确', () => {
  const answers = {
    1: 'A',
    2: [],
    3: 'true',
    4: '  ',
  }
  assert.equal(countUnanswered(QUESTIONS, answers), 2)
})

test('全部作答返回 0,全部空返回题量', () => {
  assert.equal(countUnanswered(QUESTIONS, {
    1: 'A', 2: ['A', 'B'], 3: 'false', 4: '简答内容',
  }), 0)

  assert.equal(countUnanswered(QUESTIONS, {}), 4)
  assert.equal(countUnanswered([], {}), 0)
})
