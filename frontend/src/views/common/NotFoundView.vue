<template>
  <main class="notfound">
    <div class="notfound__card">
      <p class="notfound__code">404</p>
      <h1 class="notfound__title">页面不存在</h1>
      <p class="notfound__desc">你访问的地址可能已移动、被删除，或者输入有误。</p>
      <div class="notfound__actions">
        <router-link to="/" class="notfound__btn notfound__btn--primary">返回首页</router-link>
        <router-link to="/login" class="notfound__btn">去登录</router-link>
      </div>
    </div>
  </main>
</template>

<style scoped>
.notfound {
  display: grid;
  place-items: center;
  min-height: 100vh;
  padding: var(--sp-6);
  background: var(--bg-page);
  background-image: radial-gradient(circle at 1px 1px, var(--line-100) 1px, transparent 0);
  background-size: 24px 24px;
}
.notfound__card {
  width: 100%;
  max-width: 420px;
  padding: var(--sp-8) var(--sp-6);
  text-align: center;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-md);
}
.notfound__code {
  font-family: var(--font-serif);
  font-size: 56px;
  line-height: 1;
  color: var(--accent-600);
}
.notfound__title {
  margin-top: var(--sp-4);
  font-family: var(--font-serif);
  font-size: var(--fs-xl);
  color: var(--text-primary);
}
.notfound__desc {
  margin-top: var(--sp-2);
  font-size: var(--fs-sm);
  line-height: 1.8;
  color: var(--text-secondary);
}
.notfound__actions {
  display: flex;
  justify-content: center;
  gap: var(--sp-3);
  margin-top: var(--sp-6);
}
.notfound__btn {
  padding: 10px 20px;
  font-size: var(--fs-sm);
  color: var(--text-primary);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  transition: border-color var(--dur-fast) var(--ease);
}
.notfound__btn:hover {
  border-color: var(--color-primary);
}
.notfound__btn--primary {
  color: #fff;
  background: var(--color-primary);
  border-color: var(--color-primary);
}
</style>
