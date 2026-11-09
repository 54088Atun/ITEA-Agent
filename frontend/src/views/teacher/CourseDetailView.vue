<template>
  <div class="page">
    <div class="page-head">
      <div class="page-head__main">
        <el-button link class="back-link" @click="router.back()">
          <el-icon><ArrowLeft /></el-icon> 返回
        </el-button>
        <h2 class="page-title">{{ course ? course.name : '课程管理' }}</h2>
        <p class="page-sub">维护课程知识点体系与教材资料</p>
      </div>
      <div class="page-head__actions">
        <el-button v-if="canEditInfo" @click="openAnnouncement">
          <el-icon><Bell /></el-icon> 发布公告
        </el-button>
        <el-button v-if="features.feature_course_share" @click="openShare">
          <el-icon><Share /></el-icon> 分享课程
        </el-button>
      </div>
    </div>

    <template v-if="loading && !course">
      <div class="panel"><SkeletonTable :rows="6" :cols="4" /></div>
    </template>
    <StateBlock v-else-if="error && !course" state="error" title="课程详情加载失败" @retry="load" />
    <el-tabs v-else v-model="tab">
      <!-- 基本信息 -->
      <el-tab-pane label="基本信息" name="info">
        <div class="tab-body">
          <div v-if="overview" class="overview-grid">
            <div class="ov-card">
              <span class="ov-card__label">资料</span>
              <span class="ov-card__value">{{ overview.materials.total }}</span>
              <span class="ov-card__hint">知识点 {{ overview.knowledge_points }} 个</span>
            </div>
            <div class="ov-card">
              <span class="ov-card__label">班级 / 学生</span>
              <span class="ov-card__value">{{ overview.classes.total }} / {{ overview.classes.students }}</span>
              <span class="ov-card__hint">选课 {{ overview.classes.enrollments }} 人</span>
            </div>
            <div class="ov-card">
              <span class="ov-card__label">作业</span>
              <span class="ov-card__value">{{ overview.assignments.total }}</span>
              <span class="ov-card__hint">
                草稿 {{ overview.assignments.draft }} · 待批改 {{ overview.assignments.pending_grading }}
              </span>
            </div>
            <div class="ov-card">
              <span class="ov-card__label">考试</span>
              <span class="ov-card__value">{{ overview.exams.total }}</span>
              <span class="ov-card__hint">
                草稿 {{ overview.exams.draft }} · 已发布 {{ overview.exams.published }}
              </span>
            </div>
          </div>

          <div class="panel">
            <div class="panel__head">
              <span class="panel__title">课程信息</span>
              <el-button
                v-if="canEditInfo && !editingInfo"
                type="primary" plain size="small" @click="startEditInfo"
              >
                <el-icon><EditPen /></el-icon> 修改
              </el-button>
            </div>

            <el-descriptions v-if="!editingInfo" :column="descColumns" border size="small">
              <el-descriptions-item label="课程名">{{ course?.name || '—' }}</el-descriptions-item>
              <el-descriptions-item label="课程代码">{{ course?.code || '—' }}</el-descriptions-item>
              <el-descriptions-item label="学期">{{ course?.semester || '—' }}</el-descriptions-item>
              <el-descriptions-item label="审核状态">
                <el-tag :type="auditTag(course?.audit_status)" size="small" effect="light">
                  {{ auditLabel(course?.audit_status) }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="课程简介 / 教学大纲" :span="descColumns">
                <div class="syllabus-text">{{ course?.syllabus || '暂无简介' }}</div>
              </el-descriptions-item>
            </el-descriptions>

            <el-form v-else :model="infoForm" label-position="top" class="info-form">
              <div class="info-grid">
                <el-form-item label="课程名">
                  <el-input v-model="infoForm.name" maxlength="100" placeholder="如：数据结构" />
                </el-form-item>
                <el-form-item label="课程代码">
                  <el-input v-model="infoForm.code" maxlength="20" placeholder="如：CS201" />
                </el-form-item>
                <el-form-item label="学期">
                  <el-input v-model="infoForm.semester" maxlength="20" placeholder="如：2026秋季" />
                </el-form-item>
              </div>
              <el-form-item label="课程简介 / 教学大纲">
                <el-input v-model="infoForm.syllabus" type="textarea" :rows="6" placeholder="选填" />
              </el-form-item>
              <el-form-item label="审核状态">
                <el-tag :type="auditTag(course?.audit_status)" size="small" effect="light">
                  {{ auditLabel(course?.audit_status) }}
                </el-tag>
                <span class="info-hint">课程需平台审核通过后学生才可见</span>
              </el-form-item>
              <div class="info-actions">
                <el-button @click="cancelEditInfo">取消</el-button>
                <el-button type="primary" :loading="savingInfo" @click="saveInfo">保存基本信息</el-button>
              </div>
            </el-form>
          </div>
        </div>
      </el-tab-pane>

      <!-- 知识点 -->
      <el-tab-pane label="知识点体系" name="kp">
        <div class="tab-body">
          <div class="filter-bar">
            <el-button type="primary" @click="kpDialog = true">
              <el-icon><Plus /></el-icon> 添加知识点
            </el-button>
            <el-button :loading="draftLoading" @click="triggerDraftUpload">
              <el-icon><MagicStick /></el-icon> 从目录生成
            </el-button>
            <input
              ref="draftInput"
              type="file"
              accept=".txt,.md,.docx,.xlsx"
              hidden
              @change="onDraftFile"
            />
            <div class="filter-bar__spacer"></div>
            <span class="filter-bar__count">共 {{ knowledgePoints.length }} 个知识点</span>
          </div>

          <div class="panel kp-panel">
            <p class="kp-hint">按层级折叠展示，点击节点可展开或收起</p>
            <el-tree
              v-if="kpTree.length"
              :data="kpTree"
              node-key="id"
              :props="{ label: 'name', children: 'children' }"
              :default-expanded-keys="kpRootKeys"
              :expand-on-click-node="true"
            >
              <template #default="{ data }">
                <div class="kp-node">
                  <span class="kp-node__name">{{ data.name }}</span>
                  <span v-if="data.description" class="kp-node__desc">{{ data.description }}</span>
                </div>
              </template>
            </el-tree>
            <StateBlock v-else state="empty" title="暂无知识点" />
          </div>
        </div>
      </el-tab-pane>

      <!-- 教材与资料 -->
      <el-tab-pane label="教材与资料" name="materials">
        <div class="tab-body">
          <div class="filter-bar">
            <el-button type="primary" @click="openUpload">
              <el-icon><Upload /></el-icon> 上传资料
            </el-button>
            <span class="tip">支持 PDF / DOCX / PPTX / XLSX / TXT / MD / CSV / 代码文件；图片需开启识图</span>
            <div class="filter-bar__spacer"></div>
            <span class="filter-bar__count">共 {{ materials.length }} 份资料</span>
          </div>

          <div class="panel">
            <el-table :data="materials">
              <el-table-column label="资料标题" min-width="200">
                <template #default="{ row }">
                  <el-button link type="primary" @click="openPreview(row)">{{ row.title }}</el-button>
                </template>
              </el-table-column>
              <el-table-column label="类型" width="120">
                <template #default="{ row }">
                  <el-tag :type="typeTag(row.type)" size="small" effect="light">{{ typeLabel(row.type) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="chunk_count" label="分块数" width="100">
                <template #default="{ row }">
                  <el-tag :type="row.chunk_count > 0 ? 'success' : 'info'" size="small" effect="light">
                    {{ row.chunk_count || '未入库' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="解析" width="130">
                <template #default="{ row }">
                  <el-tooltip
                    :content="row.parse_error || ''"
                    :disabled="!row.parse_error"
                    placement="top"
                  >
                    <el-tag :type="parseTag(row)" size="small" effect="light">
                      {{ parseLabel(row) }}
                    </el-tag>
                  </el-tooltip>
                </template>
              </el-table-column>
              <el-table-column label="上传时间" width="180">
                <template #default="{ row }">{{ formatTime(row.uploaded_at) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="160">
                <template #default="{ row }">
                  <el-button link type="primary" @click="openPreview(row)">查看</el-button>
                  <el-button
                    v-if="canRetryParse(row)" link type="warning"
                    @click="retryParse(row)"
                  >
                    重新解析
                  </el-button>
                </template>
              </el-table-column>
              <template #empty>
                <StateBlock state="empty" title="暂无教材资料" />
              </template>
            </el-table>
          </div>
        </div>
      </el-tab-pane>

      <!-- 协作教师 -->
      <el-tab-pane v-if="canEditInfo" label="协作教师" name="collaborators">
        <div class="tab-body">
          <div class="filter-bar">
            <el-button type="primary" @click="openAddCollaborator">
              <el-icon><Plus /></el-icon> 添加协作教师
            </el-button>
            <span class="tip">协作者可维护本课程的知识点、资料与作业；学生数据仍归课程拥有者</span>
            <div class="filter-bar__spacer"></div>
            <span class="filter-bar__count">共 {{ collaborators.length }} 位</span>
          </div>

          <div class="panel">
            <el-table :data="collaborators" v-loading="collabLoading">
              <el-table-column prop="teacher_name" label="教师" width="160" />
              <el-table-column prop="teacher_email" label="邮箱" min-width="200" />
              <el-table-column label="添加时间" width="180">
                <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="100">
                <template #default="{ row }">
                  <el-button link type="danger" @click="removeCollaborator(row)">移除</el-button>
                </template>
              </el-table-column>
              <template #empty>
                <StateBlock state="empty" title="暂无协作教师" hint="点击上方按钮搜索教师账号后添加" />
              </template>
            </el-table>
          </div>
        </div>
      </el-tab-pane>

      <!-- 课程对应的作业与考试 -->
      <el-tab-pane label="作业与考试" name="tasks">
        <div class="tab-body">
          <div class="panel">
            <div class="panel__head">
              <span class="panel__title">待批改队列</span>
              <span class="panel__hint">共 {{ gradingTotal }} 份待确认</span>
            </div>
            <el-table
              :data="gradingQueue"
              size="small"
              v-loading="gradingLoading"
              empty-text="暂无待批改提交"
            >
              <el-table-column prop="student_name" label="学生" width="110" />
              <el-table-column label="作业" min-width="200">
                <template #default="{ row }">
                  <el-button link type="primary" @click="openQueueAssignment(row)">
                    {{ row.assignment_title }}
                  </el-button>
                </template>
              </el-table-column>
              <el-table-column label="类型" width="90">
                <template #default="{ row }">
                  <el-tag size="small" effect="light" :type="row.assignment_kind === 'exam' ? 'danger' : ''">
                    {{ row.assignment_kind === 'exam' ? '考试' : '作业' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="提交时间" width="160">
                <template #default="{ row }">{{ formatTime(row.submitted_at) }}</template>
              </el-table-column>
              <el-table-column label="AI 建议" width="120">
                <template #default="{ row }">
                  <el-tag v-if="row.has_ai_suggestion" type="warning" size="small" effect="light">
                    {{ row.ai_score }} 分
                  </el-tag>
                  <span v-else class="dim">未生成</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="90">
                <template #default="{ row }">
                  <el-button link type="primary" @click="openQueueAssignment(row)">去批改</el-button>
                </template>
              </el-table-column>
            </el-table>
            <div v-if="gradingTotal > gradingPageSize" class="pager">
              <el-pagination
                v-model:current-page="gradingPage"
                :page-size="gradingPageSize"
                :total="gradingTotal"
                layout="prev, pager, next"
                @current-change="loadGradingQueue"
              />
            </div>
          </div>

          <div class="panel">
            <div class="panel__head">
              <span class="panel__title">作业</span>
              <span class="panel__hint">共 {{ courseAssignments.length }} 项</span>
            </div>
            <el-table :data="courseAssignments" size="small" empty-text="本课程暂无作业">
              <el-table-column label="作业" min-width="220">
                <template #default="{ row }">
                  <el-button link type="primary" @click="openAssignmentDetail(row)">{{ row.title }}</el-button>
                </template>
              </el-table-column>
              <el-table-column label="类型" width="90">
                <template #default="{ row }">
                  <el-tag size="small" effect="light" :type="row.kind === 'exam' ? 'danger' : ''">
                    {{ row.kind === 'exam' ? '考试' : '作业' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="截止时间" width="160">
                <template #default="{ row }">{{ formatTime(row.due_at) }}</template>
              </el-table-column>
              <el-table-column prop="submission_count" label="提交" width="80" />
              <el-table-column prop="pending_count" label="待确认" width="90" />
              <el-table-column label="状态" width="90">
                <template #default="{ row }">
                  <el-tag :type="taskStatusTag(row.status)" size="small" effect="light">
                    {{ taskStatusLabel(row.status) }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
          </div>

          <div class="panel">
            <div class="panel__head">
              <span class="panel__title">考试</span>
              <span class="panel__hint">共 {{ courseExams.length }} 份</span>
            </div>
            <el-table :data="courseExams" size="small" empty-text="本课程暂无试卷">
              <el-table-column label="试卷" min-width="220">
                <template #default="{ row }">
                  <el-button link type="primary" @click="openExamDetail(row)">{{ row.title }}</el-button>
                </template>
              </el-table-column>
              <el-table-column prop="question_count" label="题数" width="80" />
              <el-table-column prop="total_score" label="总分" width="80" />
              <el-table-column prop="submission_count" label="提交" width="80" />
              <el-table-column label="截止时间" width="160">
                <template #default="{ row }">{{ formatTime(row.due_at) }}</template>
              </el-table-column>
              <el-table-column label="状态" width="90">
                <template #default="{ row }">
                  <el-tag :type="taskStatusTag(row.status)" size="small" effect="light">
                    {{ taskStatusLabel(row.status) }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 发布课程公告 -->
    <el-dialog v-model="announceVisible" title="发布课程公告" width="520px">
      <el-form label-position="top">
        <el-form-item label="发布范围">
          <el-select
            v-model="announceForm.classId"
            clearable
            placeholder="课程下全部班级"
            style="width: 100%"
          >
            <el-option v-for="c in courseClasses" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="公告内容" required>
          <el-input
            v-model="announceForm.content"
            type="textarea"
            :rows="5"
            maxlength="2000"
            show-word-limit
            placeholder="例如：本周五前提交第三章作业，逾期不再受理"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="announceVisible = false">取消</el-button>
        <el-button type="primary" :loading="announcing" @click="submitAnnouncement">发布</el-button>
      </template>
    </el-dialog>

    <!-- 添加协作教师 -->
    <el-dialog v-model="collabDialog" title="添加协作教师" width="480px">
      <el-form label-position="top">
        <el-form-item label="选择教师" required>
          <el-select
            v-model="collabTeacherId"
            filterable
            remote
            clearable
            :remote-method="searchTeacherOptions"
            :loading="collabSearching"
            placeholder="输入姓名或邮箱搜索"
            style="width: 100%"
          >
            <el-option
              v-for="t in teacherOptions"
              :key="t.id"
              :label="`${t.name}（${t.email}）`"
              :value="t.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="collabDialog = false">取消</el-button>
        <el-button
          type="primary"
          :loading="collabSaving"
          :disabled="!collabTeacherId"
          @click="addCollaborator"
        >添加</el-button>
      </template>
    </el-dialog>

    <!-- 添加知识点 -->
    <el-dialog v-model="kpDialog" title="添加知识点" width="480px">
      <el-form :model="kpForm" label-position="top">
        <el-form-item label="知识点名" required>
          <el-input v-model="kpForm.name" placeholder="如：二叉树遍历" />
        </el-form-item>
        <el-form-item label="上级知识点">
          <el-select v-model="kpForm.parentId" clearable style="width: 100%" placeholder="不选则为顶级知识点">
            <el-option v-for="kp in knowledgePoints" :key="kp.id" :label="kp.name" :value="kp.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="kpForm.description" type="textarea" :rows="3" placeholder="选填" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="kpDialog = false">取消</el-button>
        <el-button type="primary" :loading="kpLoading" @click="addKp">添加</el-button>
      </template>
    </el-dialog>

    <!-- 上传资料 -->
    <el-dialog v-model="uploadDialog" title="上传资料" width="480px">
      <el-form :model="uploadForm" label-position="top">
        <el-form-item label="资料类型" required>
          <el-select v-model="uploadForm.type" style="width: 100%">
            <el-option label="课件" value="courseware" />
            <el-option label="教学大纲" value="syllabus" />
            <el-option label="练习题" value="exercise" />
            <el-option label="面试资料" value="interview" />
          </el-select>
        </el-form-item>
        <el-form-item label="资料标题" required>
          <el-input v-model="uploadForm.title" placeholder="请输入资料标题" />
        </el-form-item>
        <el-form-item label="文件" required>
          <el-upload
            :show-file-list="true"
            :limit="1"
            :before-upload="beforeUpload"
            :http-request="doUpload"
            :accept="uploadAccept"
          >
            <el-button type="primary" size="small" :loading="uploading">
              <el-icon><Upload /></el-icon> 选择并上传
            </el-button>
          </el-upload>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uploadDialog = false">关闭</el-button>
      </template>
    </el-dialog>
    <!-- 知识点草稿预览 -->
    <el-dialog v-model="draftVisible" title="知识点与大纲草稿" width="720px">
      <div v-if="draft" class="draft">
        <p class="draft__file">来源文件：{{ draft.filename }}</p>
        <el-checkbox v-model="applySyllabus">同时更新课程大纲</el-checkbox>
        <el-input
          v-if="applySyllabus"
          v-model="draftSyllabus"
          class="draft__syllabus"
          type="textarea"
          :rows="6"
        />
        <p class="draft__hint">勾选需要采纳的知识点；采纳后才会写入正式知识点体系，未采纳内容不会影响教学。</p>
        <el-tree
          ref="treeRef"
          :data="draftTree"
          show-checkbox
          node-key="path"
          :props="{ label: 'label', children: 'children' }"
          default-expand-all
        />
      </div>
      <template #footer>
        <el-button @click="discardDraft">丢弃草稿</el-button>
        <el-button @click="draftVisible = false">稍后处理</el-button>
        <el-button type="primary" :loading="adopting" @click="adoptSelected">采纳选中</el-button>
        <el-button type="success" :loading="adopting" @click="adoptAll">全部采纳</el-button>
      </template>
    </el-dialog>

    <!-- 分享课程 -->
    <el-dialog v-model="shareVisible" title="分享课程" width="620px">
      <el-form inline class="share-form">
        <el-form-item label="有效天数">
          <el-input-number v-model="shareForm.expires_days" :min="1" :max="365" />
        </el-form-item>
        <el-form-item label="可用次数">
          <el-input-number v-model="shareForm.max_uses" :min="1" :max="100" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="sharing" @click="createShare">生成教师课程码</el-button>
        </el-form-item>
      </el-form>
      <el-table :data="shares" size="small" v-loading="shareLoading">
        <el-table-column label="教师课程码" width="140">
          <template #default="{ row }">
            <el-button link type="primary" @click="copyShare(row.code)">{{ row.code }}</el-button>
          </template>
        </el-table-column>
        <el-table-column label="有效期至" min-width="150">
          <template #default="{ row }">{{ formatTime(row.expires_at) }}</template>
        </el-table-column>
        <el-table-column label="已用/次数" width="100">
          <template #default="{ row }">{{ row.used_count }}/{{ row.max_uses }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="shareTag(row.status)" size="small" effect="light">
              {{ shareLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button v-if="row.status === 'active'" link type="danger" @click="revokeShare(row)">撤销</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <StateBlock state="empty" title="还没有教师课程码" hint="设置有效期后点击生成" />
        </template>
      </el-table>
      <p class="share-hint">对方凭码复制为课程快照，只包含课程信息、知识点与资料元数据，不会带走本课程的学生、学情与作业数据。</p>
    </el-dialog>

    <!-- 资料预览:Office 文档由服务端转 PDF,版式与 Word/Excel/PPT 一致 -->
    <MaterialPreviewDialog
      v-model="previewVisible"
      :course-id="courseId"
      :material="previewMaterial"
    />
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { courseApi } from '../../api/course'
import { examApi } from '../../api/exams'
import { teacherApi } from '../../api/teacher'
import { classroomApi } from '../../api/classroom'
import { features, loadFeatures } from '../../stores/features'
import { useUserStore } from '../../stores/user'
import SkeletonTable from '../../components/SkeletonTable.vue'
import StateBlock from '../../components/StateBlock.vue'
import MaterialPreviewDialog from '../../components/MaterialPreviewDialog.vue'

const route = useRoute()
const router = useRouter()
const courseId = Number(route.params.id)

const loading = ref(true)
const error = ref(false)
const course = ref(null)
const tab = ref('kp')
const knowledgePoints = ref([])
const materials = ref([])
const assignments = ref([])
const exams = ref([])
const userStore = useUserStore()
const editingInfo = ref(false)
const descColumns = window.matchMedia('(max-width: 767px)').matches ? 1 : 2

// 课程概览与待批改队列
const overview = ref(null)
const gradingQueue = ref([])
const gradingTotal = ref(0)
const gradingPage = ref(1)
const gradingPageSize = 10
const gradingLoading = ref(false)

const canEditInfo = computed(() => {
  if (!course.value) return false
  return userStore.isAdmin || userStore.user?.id === course.value.teacher_id
})

// 知识点按 parent_id 构建层级,交由 el-tree 折叠展示
const kpTree = computed(() => {
  const nodes = new Map()
  knowledgePoints.value.forEach((kp) => {
    nodes.set(kp.id, { ...kp, children: [] })
  })
  const roots = []
  nodes.forEach((node) => {
    if (node.parent_id && nodes.has(node.parent_id)) {
      nodes.get(node.parent_id).children.push(node)
    } else {
      roots.push(node)
    }
  })
  return roots
})

// 默认只展开顶层，下级保持折叠，深层知识点较多的课程更清爽
const kpRootKeys = computed(() => kpTree.value.map((node) => node.id))

const courseAssignments = computed(() =>
  assignments.value.filter((item) => item.course_id === courseId),
)
const courseExams = computed(() =>
  exams.value.filter((item) => item.course_id === courseId),
)

// ---------- 课程公告 ----------
const announceVisible = ref(false)
const announcing = ref(false)
const announceForm = reactive({ classId: null, content: '' })
const courseClasses = ref([])

// ---------- 协作教师 ----------
const collaborators = ref([])
const collabLoading = ref(false)
const collabDialog = ref(false)
const collabSearching = ref(false)
const collabSaving = ref(false)
const collabTeacherId = ref(null)
const teacherOptions = ref([])

// ---------- 资料预览 ----------
const previewVisible = ref(false)
const previewMaterial = ref(null)

const kpDialog = ref(false)
const kpLoading = ref(false)
const uploading = ref(false)
const kpForm = reactive({ name: '', description: '', parentId: null })

// 基本信息
const infoForm = reactive({ name: '', code: '', semester: '', syllabus: '' })
const savingInfo = ref(false)

// 上传白名单：accept 与 beforeUpload 共用同一份，避免可选类型与实际校验不一致
const ACCEPT_EXTS = [
  '.pdf', '.docx', '.pptx', '.xlsx', '.xlsm', '.txt', '.md', '.csv',
  '.py', '.js', '.ts', '.java', '.c', '.cpp', '.h', '.sql', '.html',
  '.css', '.vue', '.json', '.xml', '.yml', '.yaml',
  '.png', '.jpg', '.jpeg', '.webp', '.bmp',
]
const uploadAccept = ACCEPT_EXTS.join(',')

const uploadDialog = ref(false)
const uploadForm = reactive({ type: 'courseware', title: '' })

// ---------- 知识点草稿 ----------
const draftInput = ref()
const draftVisible = ref(false)
const draftLoading = ref(false)
const adopting = ref(false)
const draft = ref(null)
const draftTree = ref([])
const draftSyllabus = ref('')
const applySyllabus = ref(false)
const treeRef = ref()

// ---------- 课程分享 ----------
const shareVisible = ref(false)
const sharing = ref(false)
const shareLoading = ref(false)
const shares = ref([])
const shareForm = reactive({ expires_days: 7, max_uses: 1 })

const TYPE_LABELS = {
  courseware: '课件',
  syllabus: '教学大纲',
  exercise: '练习题',
  interview: '面试资料',
}

onMounted(() => {
  load()
  if (!features.loaded) loadFeatures()
})

async function load() {
  error.value = false
  loading.value = true
  try {
    // 后端知识点/素材接口均直接返回数组
    const [c, kps, mats] = await Promise.all([
      courseApi.detail(courseId),
      courseApi.knowledgePoints(courseId),
      courseApi.materials(courseId),
    ])
    course.value = c
    fillInfo(c)
    knowledgePoints.value = Array.isArray(kps) ? kps : []
    materials.value = Array.isArray(mats) ? mats : []
    loadTasks()
    loadOverview()
    loadGradingQueue()
    loadCollaborators()
  } catch { /* 拦截器已提示 */ } finally {
    loading.value = false
  }
}

/** 课程概览：素材/知识点/班级/作业/考试一次取齐，失败不影响主流程 */
async function loadOverview() {
  try {
    overview.value = await teacherApi.courseOverview(courseId)
  } catch {
    overview.value = null
  }
}

/** 待批改队列：跨作业聚合，支持翻页 */
async function loadGradingQueue() {
  gradingLoading.value = true
  try {
    const data = await teacherApi.gradingQueue(courseId, {
      page: gradingPage.value,
      page_size: gradingPageSize,
    })
    gradingQueue.value = data.items || []
    gradingTotal.value = data.total || 0
  } catch {
    gradingQueue.value = []
    gradingTotal.value = 0
  } finally {
    gradingLoading.value = false
  }
}

function openQueueAssignment(row) {
  router.push(`/teacher/assignments/${row.assignment_id}`)
}

/** 协作教师列表:仅课程拥有者或管理员可读 */
async function loadCollaborators() {
  if (!canEditInfo.value) return
  collabLoading.value = true
  try {
    const rows = await courseApi.collaborators(courseId)
    collaborators.value = Array.isArray(rows) ? rows : []
  } catch {
    collaborators.value = []
  } finally {
    collabLoading.value = false
  }
}

function openAddCollaborator() {
  collabTeacherId.value = null
  teacherOptions.value = []
  collabDialog.value = true
  searchTeacherOptions('')
}

/** 远程搜索教师,排除课程拥有者与已有协作者 */
async function searchTeacherOptions(keyword) {
  collabSearching.value = true
  try {
    const rows = await courseApi.searchTeachers({ keyword: keyword || '', courseId })
    teacherOptions.value = Array.isArray(rows) ? rows : []
  } catch {
    teacherOptions.value = []
  } finally {
    collabSearching.value = false
  }
}

async function addCollaborator() {
  if (!collabTeacherId.value) return
  collabSaving.value = true
  try {
    await courseApi.addCollaborator(courseId, collabTeacherId.value)
    ElMessage.success('已添加协作教师')
    collabDialog.value = false
    loadCollaborators()
  } catch { /* 拦截器已提示 */ } finally {
    collabSaving.value = false
  }
}

async function removeCollaborator(row) {
  try {
    await ElMessageBox.confirm(
      `确认移除协作教师「${row.teacher_name}」？移除后其将失去本课程的维护权限。`,
      '移除协作教师',
      { type: 'warning' },
    )
  } catch { return }
  try {
    await courseApi.removeCollaborator(courseId, row.teacher_id)
    ElMessage.success('已移除')
    loadCollaborators()
  } catch { /* 拦截器已提示 */ }
}

async function openAnnouncement() {
  announceForm.classId = null
  announceForm.content = ''
  announceVisible.value = true
  if (courseClasses.value.length) return
  try {
    const rows = await classroomApi.list()
    courseClasses.value = (Array.isArray(rows) ? rows : []).filter((c) => c.course_id === courseId)
  } catch { /* 拦截器已提示 */ }
}

async function submitAnnouncement() {
  const content = announceForm.content.trim()
  if (!content) return ElMessage.warning('请输入公告内容')
  announcing.value = true
  try {
    const res = await teacherApi.publishCourseAnnouncement(
      courseId, content, announceForm.classId || null,
    )
    ElMessage.success(`公告已发布到 ${res.count} 个班级`)
    announceVisible.value = false
  } catch { /* 拦截器已提示 */ } finally {
    announcing.value = false
  }
}

async function loadTasks() {
  const [assignmentRes, examRes] = await Promise.allSettled([
    teacherApi.assignments(),
    examApi.exams(),
  ])
  if (assignmentRes.status === 'fulfilled') {
    assignments.value = Array.isArray(assignmentRes.value) ? assignmentRes.value : []
  }
  if (examRes.status === 'fulfilled') {
    exams.value = Array.isArray(examRes.value) ? examRes.value : []
  }
}

function fillInfo(c) {
  Object.assign(infoForm, {
    name: c?.name || '',
    code: c?.code || '',
    semester: c?.semester || '',
    syllabus: c?.syllabus || '',
  })
}

function auditLabel(s) {
  return { approved: '已通过', pending: '审核中', rejected: '已驳回' }[s] || '未提交审核'
}

function auditTag(s) {
  return { approved: 'success', pending: 'warning', rejected: 'danger' }[s] || 'info'
}

function startEditInfo() {
  fillInfo(course.value)
  editingInfo.value = true
}

function cancelEditInfo() {
  fillInfo(course.value)
  editingInfo.value = false
}

async function saveInfo() {
  if (!infoForm.name.trim()) return ElMessage.warning('请输入课程名')
  savingInfo.value = true
  try {
    await teacherApi.updateCourse(courseId, {
      name: infoForm.name.trim(),
      code: infoForm.code.trim(),
      semester: infoForm.semester.trim() || null,
      syllabus: infoForm.syllabus.trim() || null,
    })
    ElMessage.success('课程信息已保存')
    editingInfo.value = false
    await load()
  } catch { /* 拦截器已提示 */ } finally {
    savingInfo.value = false
  }
}

function openPreview(row) {
  previewMaterial.value = row
  previewVisible.value = true
}

function typeLabel(t) {
  return TYPE_LABELS[t] || t || '—'
}

function typeTag(t) {
  return { courseware: '', syllabus: 'success', exercise: 'warning', interview: 'danger' }[t] || 'info'
}

function formatTime(t) {
  if (!t) return '—'
  return String(t).replace('T', ' ').slice(0, 19)
}

function taskStatusLabel(status) {
  return { draft: '草稿', published: '已发布', closed: '已关闭' }[status] || status
}

function taskStatusTag(status) {
  return { draft: 'info', published: 'success', closed: 'warning' }[status] || 'info'
}

function openAssignmentDetail(row) {
  router.push(`/teacher/assignments/${row.id}`)
}

function openExamDetail(row) {
  router.push(`/teacher/exams/${row.id}`)
}

// ---------- 知识点草稿:上传 → 预览 → 选择性采纳 ----------

function triggerDraftUpload() {
  draftInput.value?.click()
}

async function onDraftFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  draftLoading.value = true
  try {
    const data = await teacherApi.createKpDraft(courseId, file)
    draft.value = data
    draftSyllabus.value = data.payload?.syllabus || ''
    applySyllabus.value = false
    draftTree.value = toTree(data.payload?.knowledge_points || [])
    draftVisible.value = true
  } catch { /* 拦截器已提示 */ } finally {
    draftLoading.value = false
  }
}

function toTree(nodes, prefix = '') {
  return (nodes || []).map((node, index) => {
    const path = prefix ? `${prefix}-${index}` : `${index}`
    const children = toTree(node.children || [], path)
    return {
      path,
      label: node.name,
      description: node.description,
      ...(children.length ? { children } : {}),
    }
  })
}

async function adoptSelected() {
  const paths = treeRef.value?.getCheckedKeys() || []
  if (!paths.length) return ElMessage.warning('请先勾选需要采纳的知识点')
  await adoptDraft({ paths, adopt_all: false })
}

async function adoptAll() {
  await adoptDraft({ adopt_all: true })
}

async function adoptDraft(payload) {
  adopting.value = true
  try {
    const res = await teacherApi.adoptKpDraft(draft.value.id, {
      ...payload,
      apply_syllabus: applySyllabus.value,
      syllabus: applySyllabus.value ? draftSyllabus.value : null,
    })
    const extra = res.skipped ? `，跳过重复 ${res.skipped} 个` : ''
    ElMessage.success(`已采纳 ${res.created} 个知识点${extra}`)
    draftVisible.value = false
    await load()
  } catch { /* 拦截器已提示 */ } finally {
    adopting.value = false
  }
}

async function discardDraft() {
  try {
    await teacherApi.discardKpDraft(draft.value.id)
    draftVisible.value = false
    ElMessage.success('草稿已丢弃')
  } catch { /* 拦截器已提示 */ }
}

async function addKp() {
  if (!kpForm.name.trim()) return ElMessage.warning('请输入知识点名')
  kpLoading.value = true
  try {
    await courseApi.addKnowledgePoint(courseId, kpForm)
    ElMessage.success('知识点已添加')
    kpDialog.value = false
    Object.assign(kpForm, { name: '', description: '', parentId: null })
    load()
  } catch { /* 拦截器已提示 */ } finally {
    kpLoading.value = false
  }
}

// ---------- 课程分享 ----------

async function openShare() {
  shareVisible.value = true
  await loadShares()
}

async function loadShares() {
  shareLoading.value = true
  try {
    const rows = await teacherApi.shares(courseId)
    shares.value = Array.isArray(rows) ? rows : []
  } catch { /* 拦截器已提示 */ } finally {
    shareLoading.value = false
  }
}

async function createShare() {
  try {
    await ElMessageBox.confirm('生成课程码后其他教师可复制本课程快照，确定生成？', '生成课程码', { type: 'warning' })
  } catch { return }
  sharing.value = true
  try {
    const res = await teacherApi.createShare(courseId, {
      expires_days: shareForm.expires_days,
      max_uses: shareForm.max_uses,
    }, true)
    ElMessage.success(`教师课程码已生成：${res.code}`)
    await loadShares()
  } catch { /* 拦截器已提示 */ } finally {
    sharing.value = false
  }
}

async function revokeShare(row) {
  try {
    await ElMessageBox.confirm('撤销后该课程码立即失效，确定撤销？', '撤销课程码', { type: 'warning' })
  } catch { return }
  try {
    await teacherApi.revokeShare(row.id, true)
    ElMessage.success('已撤销')
    await loadShares()
  } catch { /* 拦截器已提示 */ }
}

async function copyShare(code) {
  try {
    await navigator.clipboard.writeText(code)
    ElMessage.success('教师课程码已复制')
  } catch {
    ElMessage.warning(`请手动复制教师课程码：${code}`)
  }
}

function shareLabel(s) {
  return { active: '可用', expired: '已过期', exhausted: '已用完', revoked: '已撤销' }[s] || s
}

function shareTag(s) {
  return { active: 'success', expired: 'info', exhausted: 'warning', revoked: 'danger' }[s] || 'info'
}

function openUpload() {
  Object.assign(uploadForm, { type: 'courseware', title: '' })
  uploadDialog.value = true
}

function beforeUpload(file) {
  const name = (file.name || '').toLowerCase()
  const ok = ACCEPT_EXTS.some((ext) => name.endsWith(ext))
  if (!ok) ElMessage.warning('不支持该文件格式，请上传文档、代码或图片')
  if (ok && !uploadForm.title.trim()) {
    uploadForm.title = file.name.replace(/\.[^.]+$/, '')
  }
  return ok
}

async function doUpload({ file }) {
  if (!uploadForm.title.trim()) return ElMessage.warning('请填写资料标题')
  uploading.value = true
  try {
    await courseApi.uploadMaterial(courseId, uploadForm.type, uploadForm.title, file)
    ElMessage.success('上传成功，正在后台解析与审核')
    uploadDialog.value = false
    load()
    setTimeout(load, 1500)
  } catch { /* 拦截器已提示 */ } finally {
    uploading.value = false
  }
}

// ---------- 素材解析状态 ----------

function parseLabel(row) {
  const status = row.parse_status
  if (status === 'done') return '已解析'
  if (status === 'processing') return `解析中 ${row.parse_progress || 0}%`
  if (status === 'pending') return '排队中'
  if (status === 'rejected') return '审核未通过'
  if (status === 'failed') return '解析失败'
  return row.chunk_count > 0 ? '已入库' : '未解析'
}

function parseTag(row) {
  if (row.parse_status === 'done') return 'success'
  if (row.parse_status === 'rejected' || row.parse_status === 'failed') return 'danger'
  if (row.parse_status) return 'warning'
  return 'info'
}

function canRetryParse(row) {
  return ['failed', 'rejected'].includes(row.parse_status)
    || (!row.parse_status && !row.chunk_count)
}

async function retryParse(row) {
  try {
    await courseApi.retryMaterialParse(courseId, row.id)
    ElMessage.success('已重新提交解析')
    load()
  } catch { /* 拦截器已提示 */ }
}
</script>

<style scoped>
.back-link { padding: 0; margin-bottom: var(--sp-1); color: var(--text-secondary); }
.tab-body { display: flex; flex-direction: column; gap: var(--sp-4); }
.info-form :deep(.el-form-item) { margin-bottom: var(--sp-4); }
.info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 0 var(--sp-4);
}
.info-hint { margin-left: var(--sp-2); font-size: var(--fs-xs); color: var(--text-secondary); }
.syllabus-text { white-space: pre-wrap; line-height: 1.8; color: var(--text-primary); }
.info-actions { display: flex; justify-content: flex-end; gap: var(--sp-2); }
.panel__hint { margin-left: auto; font-size: var(--fs-xs); color: var(--text-secondary); }
.tip { font-size: var(--fs-xs); color: var(--text-secondary); }
.draft__file {
  margin-bottom: var(--sp-2);
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}
.draft__syllabus { margin: var(--sp-2) 0; }
.draft__hint {
  margin: var(--sp-3) 0 var(--sp-2);
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}
.dim { color: var(--text-placeholder); }

/* 课程概览卡 */
.overview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: var(--sp-3);
}
.ov-card {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--sp-4);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
}
.ov-card__label { font-size: var(--fs-xs); color: var(--text-secondary); }
.ov-card__value { font-size: var(--fs-xl); font-weight: 600; color: var(--text-primary); }
.ov-card__hint { font-size: var(--fs-xs); color: var(--text-secondary); }

.pager {
  display: flex;
  justify-content: flex-end;
  padding-top: var(--sp-3);
}
.share-form { margin-bottom: var(--sp-2); }
.share-hint { margin-top: var(--sp-3); font-size: var(--fs-xs); color: var(--text-secondary); }
.kp-panel { padding: var(--sp-4); }
.kp-hint { margin: 0 0 var(--sp-2); font-size: var(--fs-xs); color: var(--text-secondary); }
.kp-node { display: flex; align-items: baseline; gap: var(--sp-2); min-width: 0; }
.kp-node__name { color: var(--text-primary); }
.kp-node__desc {
  color: var(--text-placeholder);
  font-size: var(--fs-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
