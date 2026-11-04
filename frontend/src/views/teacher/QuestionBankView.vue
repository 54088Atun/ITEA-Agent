<template>
  <div class="page">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">题库与考试</h2>
        <p class="page-sub">维护课程题库，AI 生成草稿需你采纳；组卷后发布给班级或课程学生</p>
      </div>
      <div class="page-head__actions">
        <el-select v-model="courseId" placeholder="选择课程" filterable style="width: 200px" @change="onCourseChange">
          <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
        <el-button :disabled="!courseId" @click="openAi">
          <el-icon><MagicStick /></el-icon> AI 出题
        </el-button>
        <el-button :disabled="!courseId" @click="openPlan">
          <el-icon><TrendCharts /></el-icon> AI 科目建议
        </el-button>
        <el-button :disabled="!courseId" @click="openQuestion">
          <el-icon><Plus /></el-icon> 新增题目
        </el-button>
        <el-button type="primary" :disabled="!courseId" @click="openExam">
          <el-icon><EditPen /></el-icon> 新建试卷
        </el-button>
      </div>
    </div>

    <el-alert
      type="info" :closable="false" show-icon
      title="AI 生成的题目仅进入草稿，勾选采纳后才入题库；考试暂只支持单选/多选/判断题，提交后自动判分。"
      class="tip"
    />

    <el-tabs v-model="tab">
      <el-tab-pane label="题库" name="questions">
        <div class="panel">
          <el-table :data="questions" v-loading="loadingQuestions">
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column label="题型" width="90">
              <template #default="{ row }">
                <el-tag :type="typeTag(row.type)" size="small" effect="light">{{ typeLabel(row.type) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="stem" label="题干" min-width="260" show-overflow-tooltip />
            <el-table-column label="难度" width="110">
              <template #default="{ row }">
                <el-rate :model-value="row.difficulty" disabled :max="5" size="small" />
              </template>
            </el-table-column>
            <el-table-column label="来源" width="90">
              <template #default="{ row }">
                <el-tag :type="row.source === 'agent' ? 'warning' : 'info'" size="small" effect="plain">
                  {{ row.source === 'agent' ? 'AI' : '手动' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="90" fixed="right">
              <template #default="{ row }">
                <el-button link type="danger" @click="archiveQuestion(row)">归档</el-button>
              </template>
            </el-table-column>
            <template #empty>
              <div class="empty-state">该课程还没有题目，可手动新增或让 AI 出题</div>
            </template>
          </el-table>
        </div>
      </el-tab-pane>

      <el-tab-pane label="试卷" name="exams">
        <div class="panel">
          <el-table :data="exams" v-loading="loadingExams">
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column prop="title" label="试卷" min-width="200" />
            <el-table-column label="课程" width="150">
              <template #default="{ row }">{{ courseName(row.course_id) }}</template>
            </el-table-column>
            <el-table-column prop="question_count" label="题数" width="80" />
            <el-table-column prop="total_score" label="总分" width="80" />
            <el-table-column prop="submission_count" label="提交" width="80" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="examStatusTag(row.status)" size="small" effect="light">
                  {{ examStatusLabel(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="截止" width="160">
              <template #default="{ row }">{{ formatTime(row.due_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="230" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openResults(row)">成绩</el-button>
                <el-button v-if="row.status === 'draft'" link type="success" @click="publishExam(row)">发布</el-button>
                <el-button v-if="row.status === 'published'" link type="warning" @click="closeExam(row)">关闭</el-button>
              </template>
            </el-table-column>
            <template #empty>
              <div class="empty-state">还没有试卷，点击右上角「新建试卷」组卷</div>
            </template>
          </el-table>
        </div>
      </el-tab-pane>

      <el-tab-pane label="考试建议" name="plans">
        <div class="panel">
          <el-alert
            type="info" :closable="false" show-icon
            title="AI 按课程知识点推荐考试科目与考核项（题型/题量/分值/难度）；采纳后成为本课程考试配置，不自动组卷或发布。"
            class="tip"
          />
          <el-table :data="plans" v-loading="loadingPlans">
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column label="建议方案" min-width="200">
              <template #default="{ row }">{{ row.plan.title }}</template>
            </el-table-column>
            <el-table-column label="科目数" width="80">
              <template #default="{ row }">{{ (row.plan.subjects || []).length }}</template>
            </el-table-column>
            <el-table-column label="建议题量" width="90">
              <template #default="{ row }">{{ planQuestionCount(row.plan) }}</template>
            </el-table-column>
            <el-table-column label="建议总分" width="90">
              <template #default="{ row }">{{ row.plan.total_score }} 分</template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="planStatusTag(row.status)" size="small" effect="light">
                  {{ planStatusLabel(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="生成时间" width="160">
              <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="180" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openPlanPreview(row)">查看</el-button>
                <el-button v-if="row.status === 'draft'" link type="success" @click="adoptPlan(row)">采纳</el-button>
                <el-button v-if="row.status !== 'discarded'" link type="danger" @click="discardPlan(row)">丢弃</el-button>
              </template>
            </el-table-column>
            <template #empty>
              <div class="empty-state">还没有考试建议，点击右上角「AI 科目建议」生成</div>
            </template>
          </el-table>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 新增题目 -->
    <el-dialog v-model="questionVisible" title="新增题目" width="620px">
      <el-form label-width="90px">
        <el-form-item label="题型">
          <el-radio-group v-model="qForm.type" @change="onTypeChange">
            <el-radio-button label="single">单选</el-radio-button>
            <el-radio-button label="multiple">多选</el-radio-button>
            <el-radio-button label="judge">判断</el-radio-button>
            <el-radio-button label="short">简答</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="题干">
          <el-input v-model="qForm.stem" type="textarea" :rows="3" placeholder="请输入完整题干" />
        </el-form-item>
        <template v-if="qForm.type === 'single' || qForm.type === 'multiple'">
          <el-form-item v-for="(op, i) in qForm.options" :key="i" :label="`选项 ${op.key}`">
            <div class="option-row">
              <el-input v-model="op.text" placeholder="选项内容" />
              <el-button v-if="qForm.options.length > 2" link type="danger" @click="removeOption(i)">删除</el-button>
            </div>
          </el-form-item>
          <el-form-item>
            <el-button link type="primary" @click="addOption">+ 添加选项</el-button>
          </el-form-item>
          <el-form-item label="答案">
            <el-input v-model="qForm.answer" :placeholder="qForm.type === 'multiple' ? '如 A,B' : '如 A'" />
          </el-form-item>
        </template>
        <el-form-item v-else-if="qForm.type === 'judge'" label="答案">
          <el-radio-group v-model="qForm.answer">
            <el-radio label="true">正确</el-radio>
            <el-radio label="false">错误</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-else label="参考答案">
          <el-input v-model="qForm.answer" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="解析">
          <el-input v-model="qForm.analysis" type="textarea" :rows="2" placeholder="选填，答案解析" />
        </el-form-item>
        <el-form-item label="难度">
          <el-rate v-model="qForm.difficulty" :max="5" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="questionVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingQuestion" @click="saveQuestion">保存</el-button>
      </template>
    </el-dialog>

    <!-- AI 出题 -->
    <el-dialog v-model="aiVisible" title="AI 出题" width="520px">
      <el-form label-width="90px">
        <el-form-item label="题目数量">
          <el-input-number v-model="aiForm.count" :min="1" :max="20" />
        </el-form-item>
        <el-form-item label="题型">
          <el-checkbox-group v-model="aiForm.types">
            <el-checkbox label="single">单选</el-checkbox>
            <el-checkbox label="multiple">多选</el-checkbox>
            <el-checkbox label="judge">判断</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
      </el-form>
      <p class="hint">AI 只生成草稿，需你勾选采纳后才进入题库。</p>
      <template #footer>
        <el-button @click="aiVisible = false">取消</el-button>
        <el-button type="primary" :loading="generating" @click="generateDrafts">生成草稿</el-button>
      </template>
    </el-dialog>

    <!-- 草稿预览 -->
    <el-dialog v-model="draftVisible" title="AI 出题草稿" width="720px">
      <div v-if="draft" class="drafts">
        <p class="hint">勾选要采纳的题目；未采纳的不会进入题库。</p>
        <el-checkbox-group v-model="selectedDraft">
          <div v-for="(item, idx) in draft.items" :key="idx" class="draft-item">
            <el-checkbox :label="idx">
              <span class="draft-item__stem">{{ item.stem }}</span>
            </el-checkbox>
            <div class="draft-item__meta">
              <el-tag size="small" effect="plain">{{ typeLabel(item.type) }}</el-tag>
              <span class="dim">答案：{{ item.answer }}</span>
            </div>
            <div v-if="item.options && item.options.length" class="draft-item__options">
              <span v-for="op in item.options" :key="op.key" class="draft-item__option">
                {{ op.key }}. {{ op.text }}
              </span>
            </div>
          </div>
        </el-checkbox-group>
      </div>
      <template #footer>
        <el-button @click="discardDraft">丢弃草稿</el-button>
        <el-button @click="draftVisible = false">稍后处理</el-button>
        <el-button type="primary" :loading="adopting" @click="adoptSelected">采纳选中</el-button>
        <el-button type="success" :loading="adopting" @click="adoptAll">全部采纳</el-button>
      </template>
    </el-dialog>

    <!-- AI 考试科目建议生成 -->
    <el-dialog v-model="planVisible" title="AI 考试科目建议" width="520px">
      <el-form label-width="90px">
        <el-form-item label="考试时长">
          <el-input-number v-model="planForm.duration_minutes" :min="5" :max="300" />
          <span class="unit">分钟</span>
        </el-form-item>
        <el-form-item label="建议总分">
          <el-input-number v-model="planForm.total_score" :min="10" :max="500" />
          <span class="unit">分</span>
        </el-form-item>
      </el-form>
      <p class="hint">AI 只生成科目与考核项建议草稿，采纳后成为本课程考试配置，不会自动组卷或发布。</p>
      <template #footer>
        <el-button @click="planVisible = false">取消</el-button>
        <el-button type="primary" :loading="generatingPlan" @click="generatePlan">生成建议</el-button>
      </template>
    </el-dialog>

    <!-- 考试建议预览 -->
    <el-dialog
      v-model="planPreviewVisible"
      :title="currentPlan?.plan?.title || '考试建议'"
      width="780px"
    >
      <div v-if="currentPlan" class="plan-preview">
        <p v-if="currentPlan.plan.summary" class="hint">{{ currentPlan.plan.summary }}</p>
        <div class="plan-meta">
          <el-tag size="small" effect="light">建议时长 {{ currentPlan.plan.duration_minutes }} 分钟</el-tag>
          <el-tag size="small" effect="light">建议总分 {{ currentPlan.plan.total_score }} 分</el-tag>
          <el-tag type="warning" size="small" effect="light">
            考核项合计 {{ currentPlan.plan.planned_score }} 分
          </el-tag>
          <el-tag :type="planStatusTag(currentPlan.status)" size="small" effect="light">
            {{ planStatusLabel(currentPlan.status) }}
          </el-tag>
        </div>
        <el-table :data="currentPlan.plan.subjects" size="small">
          <el-table-column type="index" label="#" width="50" />
          <el-table-column prop="subject" label="科目/章节" min-width="140" />
          <el-table-column label="覆盖知识点" min-width="170">
            <template #default="{ row }">{{ (row.kp_names || []).join('、') || '—' }}</template>
          </el-table-column>
          <el-table-column label="考核项" min-width="220">
            <template #default="{ row }">{{ planItemsText(row.items) }}</template>
          </el-table-column>
          <el-table-column label="题数" width="70">
            <template #default="{ row }">{{ row.question_count }}</template>
          </el-table-column>
          <el-table-column label="分值" width="70">
            <template #default="{ row }">{{ row.score }}</template>
          </el-table-column>
        </el-table>
        <p class="hint">
          考核项分值按「题量 × 每题分值」估算；采纳后可在新建试卷时一键带入标题、时长与组卷说明。
        </p>
      </div>
      <template #footer>
        <el-button @click="planPreviewVisible = false">关闭</el-button>
        <el-button
          v-if="currentPlan && currentPlan.status === 'draft'"
          type="success" :loading="adoptingPlan" @click="adoptPlan(currentPlan)"
        >
          采纳建议
        </el-button>
        <el-button
          v-if="currentPlan && currentPlan.status === 'adopted'"
          type="primary" @click="usePlanForExam(currentPlan)"
        >
          用于新建试卷
        </el-button>
      </template>
    </el-dialog>

    <!-- 新建试卷 -->
    <el-dialog v-model="examVisible" title="新建试卷" width="780px">
      <el-form label-width="96px">
        <el-form-item label="试卷标题">
          <el-input v-model="examForm.title" placeholder="如：第三章 单元测验" />
        </el-form-item>
        <el-form-item v-if="examForm.description" label="组卷说明">
          <el-input v-model="examForm.description" type="textarea" :rows="4" />
        </el-form-item>
        <el-form-item label="面向班级">
          <el-select v-model="examForm.class_id" clearable placeholder="可选，优先按班级发布" style="width: 100%">
            <el-option v-for="c in classes" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="时长 / 截止">
          <el-input-number v-model="examForm.duration_minutes" :min="5" :max="300" />
          <span class="unit">分钟</span>
          <el-input-number v-model="examForm.due_days" :min="1" :max="365" class="ml" />
          <span class="unit">天后截止</span>
        </el-form-item>
        <el-form-item label="每题分值">
          <el-input-number v-model="examForm.perScore" :min="1" :max="100" />
          <span class="unit">分（应用到所选题目）</span>
        </el-form-item>
        <el-form-item label="选题">
          <div class="pick">
            <div class="pick__hint">从题库勾选题目；简答题暂不支持组卷</div>
            <el-table
              ref="pickTable"
              :data="questions" height="260"
              @selection-change="onPickChange"
            >
              <el-table-column type="selection" width="46" />
              <el-table-column label="题型" width="80">
                <template #default="{ row }">{{ typeLabel(row.type) }}</template>
              </el-table-column>
              <el-table-column prop="stem" label="题干" min-width="280" show-overflow-tooltip />
              <el-table-column label="难度" width="80">
                <template #default="{ row }">{{ row.difficulty }}</template>
              </el-table-column>
            </el-table>
          </div>
        </el-form-item>
        <el-form-item label="发布状态">
          <el-switch v-model="examForm.publish" active-text="立即发布" inactive-text="存为草稿" />
        </el-form-item>
      </el-form>
      <p class="hint">已选 {{ picked.length }} 题，总分 {{ picked.length * examForm.perScore }} 分。</p>
      <template #footer>
        <el-button @click="examVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingExam" @click="saveExam">保存试卷</el-button>
      </template>
    </el-dialog>

    <!-- 成绩 -->
    <el-drawer v-model="resultsVisible" :title="`成绩 · ${currentExam?.title || ''}`" size="760px">
      <div v-loading="resultsLoading">
        <p class="hint">总分 {{ results.total_score }} · 已提交 {{ results.submission_count }} 人</p>
        <el-table :data="results.items" size="small">
          <el-table-column prop="student_name" label="学生" width="120" />
          <el-table-column label="得分" width="90">
            <template #default="{ row }">{{ row.score }}</template>
          </el-table-column>
          <el-table-column label="正确题数" width="110">
            <template #default="{ row }">{{ row.correct_count }} / {{ row.question_count }}</template>
          </el-table-column>
          <el-table-column label="待批改" width="90">
            <template #default="{ row }">
              <span v-if="row.pending_manual">{{ row.pending_manual }} 题</span>
              <span v-else class="dim">—</span>
            </template>
          </el-table-column>
          <el-table-column label="切屏" width="70">
            <template #default="{ row }">
              <el-tag v-if="row.violations" type="danger" size="small" effect="light">
                {{ row.violations }}
              </el-tag>
              <span v-else class="dim">0</span>
            </template>
          </el-table-column>
          <el-table-column label="复制" width="70">
            <template #default="{ row }">{{ row.copy_count || 0 }}</template>
          </el-table-column>
          <el-table-column label="粘贴" width="70">
            <template #default="{ row }">{{ row.paste_count || 0 }}</template>
          </el-table-column>
          <el-table-column label="提交时间" min-width="150">
            <template #default="{ row }">{{ formatTime(row.submitted_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="90" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openGrade(row)">批改</el-button>
            </template>
          </el-table-column>
          <template #empty>
            <div class="empty-state">暂无学生提交</div>
          </template>
        </el-table>
      </div>
    </el-drawer>

    <!-- 简答批改 -->
    <el-drawer v-model="gradeVisible" :title="`批改 · ${gradeRecord?.student_name || ''}`" size="680px">
      <div v-if="gradeRecord" class="grade" v-loading="gradeLoading">
        <div class="grade__meta">
          <el-tag size="small" effect="light">客观题 {{ gradeRecord.objective_score }} 分</el-tag>
          <el-tag size="small" effect="light">简答 {{ gradeRecord.short_score }} 分</el-tag>
          <el-tag v-if="gradeRecord.violations" type="danger" size="small" effect="light">
            切屏 {{ gradeRecord.violations }} 次
          </el-tag>
          <el-tag v-if="gradeRecord.copy_count" type="warning" size="small" effect="light">
            复制 {{ gradeRecord.copy_count }} 次
          </el-tag>
          <el-tag v-if="gradeRecord.paste_count" type="warning" size="small" effect="light">
            粘贴 {{ gradeRecord.paste_count }} 次
          </el-tag>
          <el-tag v-if="gradeRecord.timed_out" type="warning" size="small" effect="light">超时提交</el-tag>
        </div>

        <div v-for="(q, i) in gradeRecord.questions" :key="q.id" class="grade-item">
          <div class="grade-item__head">
            <span>{{ i + 1 }}.</span>
            <el-tag size="small" effect="plain">{{ typeLabel(q.type) }}</el-tag>
            <span class="grade-item__stem">{{ q.stem }}</span>
            <span class="dim">{{ q.score }} 分</span>
          </div>
          <div class="grade-item__answer">学生作答：{{ q.my_answer || '未作答' }}</div>
          <template v-if="q.type === 'short'">
            <div class="grade-item__ref">参考答案：{{ q.answer || '未提供' }}</div>
            <div v-if="q.ai_suggestion" class="grade-item__ai">
              AI 建议：{{ q.ai_suggestion.score }} 分 · {{ q.ai_suggestion.feedback }}
              <el-tag type="warning" size="small" effect="light">待确认</el-tag>
            </div>
            <div class="grade-item__score">
              得分：<el-input-number v-model="shortScores[q.id]" :min="0" :max="q.score" size="small" />
              <span class="dim">/ {{ q.score }} 分</span>
            </div>
          </template>
          <div v-else class="grade-item__result">
            {{ q.correct ? '正确' : (q.type === 'multiple' && q.awarded > 0 ? '部分正确' : '错误') }} · 得 {{ q.awarded }} 分
          </div>
        </div>

        <div class="grade__actions">
          <el-button :loading="aiGrading" @click="aiGradeRecord">AI 批改简答</el-button>
          <el-button type="primary" :loading="confirming" @click="confirmGrade">确认简答得分</el-button>
        </div>
        <p class="hint">AI 只给建议，需你确认后才写入成绩。</p>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { examApi } from '../../api/exams'
import { teacherApi } from '../../api/teacher'
import { classroomApi } from '../../api/classroom'

const courses = ref([])
const classes = ref([])
const courseId = ref(null)
const tab = ref('questions')

const questions = ref([])
const exams = ref([])
const loadingQuestions = ref(false)
const loadingExams = ref(false)

const questionVisible = ref(false)
const savingQuestion = ref(false)
const qForm = reactive({
  type: 'single', stem: '', options: [], answer: '', analysis: '', difficulty: 3,
})

const aiVisible = ref(false)
const generating = ref(false)
const aiForm = reactive({ count: 5, types: ['single', 'multiple', 'judge'] })
const draftVisible = ref(false)
const draft = ref(null)
const selectedDraft = ref([])
const adopting = ref(false)

const plans = ref([])
const loadingPlans = ref(false)
const planVisible = ref(false)
const generatingPlan = ref(false)
const planForm = reactive({ duration_minutes: 90, total_score: 100 })
const planPreviewVisible = ref(false)
const currentPlan = ref(null)
const adoptingPlan = ref(false)

const examVisible = ref(false)
const savingExam = ref(false)
const examForm = reactive({
  title: '', description: '', class_id: null, duration_minutes: 60, due_days: 7,
  perScore: 5, publish: true,
})
const picked = ref([])
const pickTable = ref()

const resultsVisible = ref(false)
const resultsLoading = ref(false)
const currentExam = ref(null)
const results = reactive({ total_score: 0, submission_count: 0, items: [] })

const gradeVisible = ref(false)
const gradeRecord = ref(null)
const gradeLoading = ref(false)
const shortScores = ref({})
const aiGrading = ref(false)
const confirming = ref(false)

const TYPE_LABELS = { single: '单选', multiple: '多选', judge: '判断', short: '简答' }

onMounted(async () => {
  try {
    const data = await teacherApi.courses()
    courses.value = Array.isArray(data) ? data : []
    if (courses.value.length) courseId.value = courses.value[0].id
  } catch { /* 拦截器已提示 */ }
  try {
    const data = await classroomApi.list()
    classes.value = Array.isArray(data) ? data : []
  } catch { /* 拦截器已提示 */ }
  await Promise.all([loadQuestions(), loadExams(), loadPlans()])
})

function onCourseChange() {
  loadQuestions()
  loadPlans()
}

function courseName(id) {
  return courses.value.find((c) => c.id === id)?.name || '—'
}

function typeLabel(t) {
  return TYPE_LABELS[t] || t
}

function typeTag(t) {
  return { single: '', multiple: 'success', judge: 'warning', short: 'info' }[t] || 'info'
}

function examStatusLabel(s) {
  return { draft: '草稿', published: '已发布', closed: '已关闭' }[s] || s
}

function examStatusTag(s) {
  return { draft: 'info', published: 'success', closed: 'warning' }[s] || 'info'
}

function planStatusLabel(s) {
  return { draft: '待采纳', adopted: '已采纳', discarded: '已丢弃' }[s] || s
}

function planStatusTag(s) {
  return { draft: 'info', adopted: 'success', discarded: 'warning' }[s] || 'info'
}

function formatTime(t) {
  if (!t) return '不限'
  return String(t).replace('T', ' ').slice(0, 16)
}

async function loadQuestions() {
  if (!courseId.value) return
  loadingQuestions.value = true
  try {
    const rows = await examApi.questions(courseId.value, { limit: 300 })
    questions.value = Array.isArray(rows) ? rows : []
  } catch { /* 拦截器已提示 */ } finally {
    loadingQuestions.value = false
  }
}

async function loadExams() {
  loadingExams.value = true
  try {
    const rows = await examApi.exams()
    exams.value = Array.isArray(rows) ? rows : []
  } catch { /* 拦截器已提示 */ } finally {
    loadingExams.value = false
  }
}

async function loadPlans() {
  if (!courseId.value) {
    plans.value = []
    return
  }
  loadingPlans.value = true
  try {
    const rows = await examApi.examPlanDrafts(courseId.value)
    plans.value = Array.isArray(rows) ? rows : []
  } catch { /* 拦截器已提示 */ } finally {
    loadingPlans.value = false
  }
}

// ---------- 题目 ----------

function openQuestion() {
  Object.assign(qForm, {
    type: 'single', stem: '', answer: '', analysis: '', difficulty: 3,
    options: [
      { key: 'A', text: '' }, { key: 'B', text: '' },
      { key: 'C', text: '' }, { key: 'D', text: '' },
    ],
  })
  questionVisible.value = true
}

function onTypeChange(type) {
  if (type === 'judge') {
    qForm.answer = 'true'
    qForm.options = []
  } else if (type === 'short') {
    qForm.options = []
    qForm.answer = ''
  } else if (!qForm.options.length) {
    qForm.options = [
      { key: 'A', text: '' }, { key: 'B', text: '' },
      { key: 'C', text: '' }, { key: 'D', text: '' },
    ]
  }
}

function addOption() {
  qForm.options.push({ key: String.fromCharCode(65 + qForm.options.length), text: '' })
}

function removeOption(index) {
  qForm.options.splice(index, 1)
  qForm.options.forEach((op, i) => { op.key = String.fromCharCode(65 + i) })
}

async function saveQuestion() {
  if (!qForm.stem.trim()) return ElMessage.warning('请输入题干')
  if (!qForm.answer.trim()) return ElMessage.warning('请填写答案')
  const options = qForm.type === 'single' || qForm.type === 'multiple'
    ? qForm.options.filter((o) => o.text.trim()).map((o) => ({ key: o.key, text: o.text.trim() }))
    : []
  savingQuestion.value = true
  try {
    await examApi.createQuestion({
      course_id: courseId.value,
      type: qForm.type,
      stem: qForm.stem.trim(),
      options,
      answer: qForm.answer.trim(),
      analysis: qForm.analysis || null,
      difficulty: qForm.difficulty,
    })
    ElMessage.success('题目已保存')
    questionVisible.value = false
    loadQuestions()
  } catch { /* 拦截器已提示 */ } finally {
    savingQuestion.value = false
  }
}

async function archiveQuestion(row) {
  try {
    await ElMessageBox.confirm('归档后不再出现在组卷列表，确定归档？', '归档题目', { type: 'warning' })
  } catch { return }
  try {
    await examApi.archiveQuestion(row.id)
    ElMessage.success('已归档')
    loadQuestions()
  } catch { /* 拦截器已提示 */ }
}

// ---------- AI 出题 ----------

function openAi() {
  aiVisible.value = true
}

async function generateDrafts() {
  generating.value = true
  try {
    const data = await examApi.createQuestionDrafts(courseId.value, {
      count: aiForm.count,
      types: aiForm.types,
    })
    draft.value = { id: data.id, items: data.items }
    selectedDraft.value = []
    aiVisible.value = false
    draftVisible.value = true
  } catch { /* 拦截器已提示 */ } finally {
    generating.value = false
  }
}

async function adoptSelected() {
  if (!selectedDraft.value.length) return ElMessage.warning('请先勾选要采纳的题目')
  await adoptDraft({ indices: selectedDraft.value })
}

async function adoptAll() {
  await adoptDraft({ adopt_all: true })
}

async function adoptDraft(payload) {
  adopting.value = true
  try {
    const res = await examApi.adoptDraft(draft.value.id, payload)
    ElMessage.success(`已采纳 ${res.created} 道题目`)
    draftVisible.value = false
    loadQuestions()
  } catch { /* 拦截器已提示 */ } finally {
    adopting.value = false
  }
}

async function discardDraft() {
  try {
    await examApi.discardDraft(draft.value.id)
    draftVisible.value = false
    ElMessage.success('草稿已丢弃')
  } catch { /* 拦截器已提示 */ }
}

// ---------- 考试科目/考核项建议 ----------

function planQuestionCount(plan) {
  return (plan.subjects || []).reduce((total, s) => total + (s.question_count || 0), 0)
}

function planItemsText(items) {
  return (items || [])
    .map((item) => `${typeLabel(item.type)} ${item.count}×${item.score}分`)
    .join(' · ')
}

function planDescription(plan) {
  const lines = [`AI 考试建议：${plan.title}`]
  if (plan.summary) lines.push(plan.summary)
  ;(plan.subjects || []).forEach((s, i) => {
    const kp = (s.kp_names || []).length ? `（${s.kp_names.join('、')}）` : ''
    lines.push(`${i + 1}. ${s.subject}${kp}：${planItemsText(s.items)}`)
  })
  return lines.join('\n')
}

function openPlan() {
  Object.assign(planForm, { duration_minutes: 90, total_score: 100 })
  planVisible.value = true
}

async function generatePlan() {
  generatingPlan.value = true
  try {
    const data = await examApi.createExamPlanDraft(courseId.value, {
      duration_minutes: planForm.duration_minutes,
      total_score: planForm.total_score,
    })
    planVisible.value = false
    currentPlan.value = data
    planPreviewVisible.value = true
    loadPlans()
  } catch { /* 拦截器已提示 */ } finally {
    generatingPlan.value = false
  }
}

function openPlanPreview(row) {
  currentPlan.value = row
  planPreviewVisible.value = true
}

async function adoptPlan(row) {
  try {
    await ElMessageBox.confirm(
      `采纳后「${row.plan.title}」将成为本课程考试配置（不会自动组卷或发布）。`,
      '采纳考试建议',
      { type: 'warning' },
    )
  } catch { return }
  adoptingPlan.value = true
  try {
    const data = await examApi.adoptExamPlanDraft(row.id)
    currentPlan.value = data
    ElMessage.success('已采纳，可在新建试卷时参考')
    loadPlans()
  } catch { /* 拦截器已提示 */ } finally {
    adoptingPlan.value = false
  }
}

async function discardPlan(row) {
  try {
    await ElMessageBox.confirm('丢弃后该建议不再作为考试配置使用，确定丢弃？', '丢弃建议', { type: 'warning' })
  } catch { return }
  try {
    await examApi.discardExamPlanDraft(row.id)
    ElMessage.success('已丢弃')
    if (currentPlan.value?.id === row.id) planPreviewVisible.value = false
    loadPlans()
  } catch { /* 拦截器已提示 */ }
}

function usePlanForExam(row) {
  planPreviewVisible.value = false
  openExam()
  examForm.title = row.plan.title
  examForm.duration_minutes = row.plan.duration_minutes
  examForm.description = planDescription(row.plan)
  ElMessage.info('已带入建议标题、时长与组卷说明，请选择题目后保存')
}

// ---------- 试卷 ----------

function openExam() {
  Object.assign(examForm, {
    title: '', description: '', class_id: null, duration_minutes: 60, due_days: 7,
    perScore: 5, publish: true,
  })
  picked.value = []
  examVisible.value = true
  loadQuestions()
}

function onPickChange(rows) {
  picked.value = rows
}

async function saveExam() {
  if (!examForm.title.trim()) return ElMessage.warning('请输入试卷标题')
  if (!picked.value.length) return ElMessage.warning('请至少勾选一道题目')
  savingExam.value = true
  try {
    await examApi.createExam({
      title: examForm.title.trim(),
      course_id: courseId.value,
      class_id: examForm.class_id || null,
      description: examForm.description || null,
      duration_minutes: examForm.duration_minutes,
      due_days: examForm.due_days,
      questions: picked.value.map((q) => ({ question_id: q.id, score: examForm.perScore })),
      publish: examForm.publish,
    })
    ElMessage.success(examForm.publish ? '试卷已发布' : '已存为草稿')
    examVisible.value = false
    loadExams()
  } catch { /* 拦截器已提示 */ } finally {
    savingExam.value = false
  }
}

async function publishExam(row) {
  try {
    await ElMessageBox.confirm('发布后学生将收到通知并可开始作答，确定发布？', '发布试卷', { type: 'warning' })
  } catch { return }
  try {
    await examApi.publishExam(row.id, true)
    ElMessage.success('已发布')
    loadExams()
  } catch { /* 拦截器已提示 */ }
}

async function closeExam(row) {
  try {
    await ElMessageBox.confirm('关闭后学生不能再提交，并会展示答案与解析，确定关闭？', '关闭试卷', { type: 'warning' })
  } catch { return }
  try {
    await examApi.closeExam(row.id, true)
    ElMessage.success('已关闭')
    loadExams()
  } catch { /* 拦截器已提示 */ }
}

async function openResults(row) {
  currentExam.value = row
  resultsVisible.value = true
  resultsLoading.value = true
  try {
    const data = await examApi.examResults(row.id)
    Object.assign(results, {
      total_score: data.total_score,
      submission_count: data.submission_count,
      items: data.items || [],
    })
  } catch { /* 拦截器已提示 */ } finally {
    resultsLoading.value = false
  }
}

// ---------- 简答批改 ----------

async function openGrade(row) {
  gradeVisible.value = true
  gradeRecord.value = null
  gradeLoading.value = true
  try {
    const data = await examApi.examRecord(row.record_id)
    gradeRecord.value = data
    const init = {}
    for (const q of data.questions) {
      if (q.type === 'short') {
        init[q.id] = q.awarded != null ? q.awarded : (q.ai_suggestion?.score ?? 0)
      }
    }
    shortScores.value = init
  } catch { /* 拦截器已提示 */ } finally {
    gradeLoading.value = false
  }
}

async function aiGradeRecord() {
  aiGrading.value = true
  try {
    await examApi.aiGradeRecord(gradeRecord.value.record_id)
    ElMessage.success('AI 建议已生成，请核对后确认')
    await openGrade({ record_id: gradeRecord.value.record_id })
  } catch { /* 拦截器已提示 */ } finally {
    aiGrading.value = false
  }
}

async function confirmGrade() {
  confirming.value = true
  try {
    const res = await examApi.confirmRecord(gradeRecord.value.record_id, shortScores.value)
    ElMessage.success(`已确认，当前总分 ${res.score}`)
    await openResults(currentExam.value)
    await openGrade({ record_id: gradeRecord.value.record_id })
  } catch { /* 拦截器已提示 */ } finally {
    confirming.value = false
  }
}
</script>

<style scoped>
.tip { margin-bottom: var(--sp-3); }
.option-row { display: flex; align-items: center; gap: var(--sp-2); width: 100%; }
.unit { margin-left: var(--sp-2); font-size: var(--fs-xs); color: var(--text-secondary); }
.ml { margin-left: var(--sp-3); }
.hint { font-size: var(--fs-xs); color: var(--text-secondary); }
.dim { color: var(--text-placeholder); }
.drafts { max-height: 420px; overflow: auto; }
.draft-item { padding: var(--sp-2) 0; border-bottom: 1px dashed var(--border); }
.draft-item__stem { color: var(--text-primary); }
.draft-item__meta { display: flex; align-items: center; gap: var(--sp-2); font-size: var(--fs-xs); margin: 4px 0 0 24px; }
.draft-item__options { display: flex; flex-wrap: wrap; gap: var(--sp-3); margin: 4px 0 0 24px; font-size: var(--fs-xs); color: var(--text-secondary); }
.plan-preview { display: flex; flex-direction: column; gap: var(--sp-2); }
.plan-meta { display: flex; align-items: center; gap: var(--sp-2); flex-wrap: wrap; }
.pick { width: 100%; }
.pick__hint { margin-bottom: var(--sp-1); font-size: var(--fs-xs); color: var(--text-secondary); }
.grade { display: flex; flex-direction: column; gap: var(--sp-3); }
.grade__meta { display: flex; align-items: center; gap: var(--sp-2); flex-wrap: wrap; }
.grade-item { padding: var(--sp-2) 0; border-bottom: 1px dashed var(--border); }
.grade-item__head { display: flex; align-items: baseline; gap: var(--sp-2); font-size: var(--fs-sm); }
.grade-item__stem { flex: 1; color: var(--text-primary); }
.grade-item__answer,
.grade-item__ref,
.grade-item__result {
  margin: 6px 0 0 16px;
  font-size: var(--fs-xs);
  color: var(--text-secondary);
  white-space: pre-wrap;
}
.grade-item__ai {
  margin: 6px 0 0 16px;
  padding: var(--sp-2);
  font-size: var(--fs-xs);
  background: var(--bg-subtle);
  border-radius: var(--r-sm);
}
.grade-item__score { margin: 8px 0 0 16px; display: flex; align-items: center; gap: var(--sp-2); font-size: var(--fs-xs); }
.grade__actions { display: flex; gap: var(--sp-2); padding-top: var(--sp-2); }
</style>
