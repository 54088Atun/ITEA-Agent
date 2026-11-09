<template>
  <div class="auth">
    <!-- 左侧品牌区：学院蓝 + 衬线标题，克制不喧哗 -->
    <section class="auth__intro">
      <div class="auth__intro-inner">
        <div class="auth__seal">
          <span class="auth__mark">I</span>
          <span class="auth__seal-text">ITEA</span>
        </div>
        <h1 class="auth__slogan">师生一体的<br />智能教学空间</h1>
        <p class="auth__desc">
          以 AI 助教串联备课、答疑、错题复盘与学情分析，
          让教与学的过程都可被记录、被理解。
        </p>
        <ul class="auth__points">
          <li><span>01</span>课程助教 · 流式答疑与思路引导</li>
          <li><span>02</span>错题复盘 · 遗忘曲线自动排程</li>
          <li><span>03</span>学情看板 · 知识点掌握度可视化</li>
        </ul>
      </div>
      <div class="auth__intro-foot">ITEA · Intelligent Teaching Ecosystem Assistant</div>
    </section>

    <!-- 右侧表单区 -->
    <section class="auth__panel">
      <div class="auth__card">
        <router-link to="/" class="auth__back">
          <el-icon><ArrowLeft /></el-icon>
          返回首页
        </router-link>

        <header class="auth__card-head">
          <h2>{{ tab === 'login' ? '登录' : '创建账号' }}</h2>
          <p>{{ tab === 'login' ? '使用校园邮箱进入你的工作空间' : '注册后可直接进入对应身份的工作台' }}</p>
        </header>

        <el-tabs v-model="tab" stretch class="auth__tabs" @tab-change="clearLoginError">
          <el-tab-pane label="登录" name="login">
            <el-form ref="loginFormRef" :model="loginForm" :rules="loginRules" label-position="top" @keyup.enter="doLogin">
              <el-alert
                v-if="loginError"
                class="auth__error"
                :title="loginError"
                type="error"
                :closable="false"
                show-icon
              />
              <el-form-item prop="email" label="邮箱">
                <el-input v-model="loginForm.email" placeholder="name@campus.edu" size="large" :prefix-icon="Message" @input="clearLoginError" />
              </el-form-item>
              <el-form-item prop="password" label="密码">
                <el-input v-model="loginForm.password" type="password" placeholder="请输入密码" size="large" :prefix-icon="Lock" show-password @input="clearLoginError" />
              </el-form-item>
              <el-button type="primary" size="large" class="auth__submit" :loading="loading" @click="doLogin">
                登 录
              </el-button>
            </el-form>
          </el-tab-pane>

          <el-tab-pane label="注册" name="register">
            <el-form ref="regFormRef" :model="regForm" :rules="regRules" label-position="top" @keyup.enter="doRegister">
              <el-form-item prop="name" label="姓名">
                <el-input v-model="regForm.name" placeholder="请输入姓名" size="large" :prefix-icon="User" />
              </el-form-item>
              <el-form-item prop="email" label="邮箱">
                <el-input v-model="regForm.email" placeholder="name@campus.edu" size="large" :prefix-icon="Message" />
              </el-form-item>
              <el-form-item prop="password" label="密码">
                <el-input v-model="regForm.password" type="password" placeholder="至少 6 位" size="large" :prefix-icon="Lock" show-password />
              </el-form-item>
              <el-form-item label="身份">
                <el-tag type="info" size="large">学生账号</el-tag>
                <p class="auth__role-tip">教师账号需由管理员开通</p>
              </el-form-item>
              <el-button type="primary" size="large" class="auth__submit" :loading="loading" @click="doRegister">
                注 册
              </el-button>
            </el-form>
          </el-tab-pane>
        </el-tabs>
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Message, Lock, User } from '@element-plus/icons-vue'
import { useUserStore } from '../../stores/user'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

// 首页双入口通过 query 预选身份与页签：?role=teacher&mode=register
// 公开注册仅开放学生;教师账号需管理员开通
const initialRole = 'student'
const tab = ref(route.query.mode === 'register' ? 'register' : 'login')
const loading = ref(false)
const loginError = ref('')
const loginFormRef = ref()
const regFormRef = ref()

const loginForm = reactive({ email: '', password: '' })
const regForm = reactive({ name: '', email: '', password: '', role: initialRole })

const loginRules = {
  email: [{ required: true, message: '请输入邮箱', trigger: 'blur' }, { type: 'email', message: '邮箱格式不正确', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}
const regRules = {
  name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
  email: [{ required: true, message: '请输入邮箱', trigger: 'blur' }, { type: 'email', message: '邮箱格式不正确', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }, { min: 6, message: '密码至少6位', trigger: 'blur' }],
  role: [{ required: true, message: '请选择角色', trigger: 'change' }],
}

function clearLoginError() {
  loginError.value = ''
}

async function doLogin() {
  // 校验失败是正常分支,不能变成未处理的 Promise rejection
  const valid = await loginFormRef.value.validate().catch(() => false)
  if (!valid) return
  loginError.value = ''
  loading.value = true
  try {
    await userStore.login(loginForm.email, loginForm.password)
    ElMessage.success('登录成功')
    router.push(userStore.homePath)
  } catch (err) {
    // 登录接口错误由页面内提示,不走全局弹窗,避免重复打扰
    const status = err?.response?.status
    const detail = err?.response?.data?.detail
    if (status === 401) {
      loginError.value = '账号或密码错误，请重新输入'
    } else if (status === 403) {
      loginError.value = typeof detail === 'string' ? detail : '账号已被禁用，请联系管理员'
    } else if (!err?.response) {
      loginError.value = '无法连接服务器，请稍后重试'
    } else {
      loginError.value = typeof detail === 'string' ? detail : '登录失败，请稍后重试'
    }
  } finally {
    loading.value = false
  }
}

async function doRegister() {
  const valid = await regFormRef.value.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    await userStore.register(regForm)
    ElMessage.success('注册成功,已自动登录')
    router.push(userStore.homePath)
  } catch { /* 拦截器已提示 */ } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 0.9fr);
  height: 100vh;
  background: var(--bg-page);
}

/* ===== 品牌区 ===== */
.auth__intro {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: var(--sp-9) var(--sp-8);
  background: var(--bg-sidebar);
  color: #fff;
  overflow: hidden;
}
/* 缓速漂移的冷光斑：让品牌区有生命力，但不做夸张动效 */
@keyframes auth-float {
  from { transform: translate3d(0, 0, 0) scale(1); }
  to { transform: translate3d(-42px, 38px, 0) scale(1.08); }
}
.auth__intro::before {
  content: '';
  position: absolute;
  top: -170px;
  right: -130px;
  width: 520px;
  height: 520px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(122, 178, 221, 0.32), transparent 66%);
  animation: auth-float 16s ease-in-out infinite alternate;
  pointer-events: none;
}
/* 极淡的讲义横线纹理，替代大块渐变 */
.auth__intro::after {
  content: '';
  position: absolute;
  inset: 0;
  background-image: repeating-linear-gradient(
    to bottom,
    rgba(255, 255, 255, 0.035) 0 1px,
    transparent 1px 46px
  );
  pointer-events: none;
}
.auth__intro-inner {
  position: relative;
  z-index: 1;
  max-width: 460px;
}
.auth__seal {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  margin-bottom: var(--sp-8);
}
.auth__mark {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border-radius: var(--r-sm);
  border: 1px solid rgba(169, 118, 47, 0.6);
  background: rgba(255, 255, 255, 0.08);
  font-family: var(--font-serif);
  font-size: 21px;
  color: var(--accent-100);
}
.auth__seal-text {
  font-size: var(--fs-sm);
  letter-spacing: 0.32em;
  color: rgba(255, 255, 255, 0.72);
}
.auth__slogan {
  font-family: var(--font-serif);
  font-size: 40px;
  font-weight: 600;
  line-height: 1.28;
  letter-spacing: 0.02em;
  color: #fff;
}
.auth__desc {
  margin-top: var(--sp-5);
  max-width: 380px;
  font-size: var(--fs-sm);
  line-height: 1.9;
  color: rgba(255, 255, 255, 0.62);
}
.auth__points {
  list-style: none;
  margin-top: var(--sp-8);
  border-top: 1px solid rgba(255, 255, 255, 0.12);
  padding-top: var(--sp-5);
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.auth__points li {
  display: flex;
  align-items: baseline;
  gap: var(--sp-3);
  font-size: var(--fs-sm);
  color: rgba(255, 255, 255, 0.78);
}
.auth__points span {
  font-family: var(--font-serif);
  font-size: var(--fs-xs);
  letter-spacing: 0.1em;
  color: var(--accent-600);
}
.auth__intro-foot {
  position: relative;
  z-index: 1;
  font-size: 10px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.3);
}

/* ===== 表单区 ===== */
.auth__panel {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--sp-8) var(--sp-6);
  /* 极淡点阵，避免右侧大面积纯白 */
  background-image: radial-gradient(circle at 1px 1px, var(--line-100) 1px, transparent 0);
  background-size: 24px 24px;
}
.auth__card {
  position: relative;
  overflow: hidden;
  width: 100%;
  max-width: 384px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-md);
  padding: var(--sp-7) var(--sp-6) var(--sp-6);
  animation: page-in var(--dur-slow) var(--ease-out) both;
}
/* 卡片顶部一条品牌渐变线，替代额外的装饰图形 */
.auth__card::before {
  content: '';
  position: absolute;
  inset: 0 0 auto 0;
  height: 3px;
  background: var(--grad-brand);
}
.auth__back {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-bottom: var(--sp-4);
  font-size: var(--fs-xs);
  color: var(--text-secondary);
  transition: color var(--dur-fast) var(--ease);
}
.auth__back:hover {
  color: var(--color-primary);
}
.auth__card-head h2 {
  font-family: var(--font-serif);
  font-size: var(--fs-xl);
  font-weight: 600;
  color: var(--text-primary);
}
.auth__card-head p {
  margin-top: var(--sp-1);
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}
.auth__tabs {
  margin-top: var(--sp-5);
}
.auth__tabs :deep(.el-tabs__header) {
  margin-bottom: var(--sp-5);
}
.auth__tabs :deep(.el-tabs__nav-wrap::after) {
  height: 1px;
  background: var(--border);
}
.auth__tabs :deep(.el-tabs__item) {
  font-size: var(--fs-base);
}
.auth__tabs :deep(.el-form-item) {
  margin-bottom: var(--sp-4);
}
.auth__error {
  margin-bottom: var(--sp-4);
}
.auth__error :deep(.el-alert__title) {
  font-size: var(--fs-sm);
  line-height: 1.6;
}
.auth__role-tip {
  margin-top: 4px;
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}
.auth__tabs :deep(.el-form-item__label) {
  font-size: var(--fs-xs);
  color: var(--text-secondary);
  padding-bottom: 4px;
}
.auth__submit {
  width: 100%;
  margin-top: var(--sp-2);
  letter-spacing: 0.2em;
  font-weight: 600;
}
.auth__role {
  width: 100%;
  display: flex;
}
.auth__role :deep(.el-radio-button) {
  flex: 1;
}
.auth__role :deep(.el-radio-button__inner) {
  width: 100%;
}

@media (max-width: 960px) {
  .auth {
    grid-template-columns: 1fr;
  }
  .auth__intro {
    display: none;
  }
}
</style>
