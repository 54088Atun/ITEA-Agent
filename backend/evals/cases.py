"""P2-1 金标准任务集

每条任务固定四个要素:
- 期望分支(branch):teacher / tutor / review / interview / admin / team / block
- 期望工具(tools):本轮应当用到的能力,用于工具选择指标
- 引用要求(citation):required 必须有课程来源;general_only 不得冒充课程来源;none 不校验
- 拒答预期(refusal):学生索要未截止作业/考试答案时必须走拦截分支

任务按角色分组,学生 48 条、教师 40 条、管理员 25 条、协作 2 条,共 115 条;
"""

_ROLE_FORBIDDEN = {
    "student": (
        "code_executor",
        "doc_generator", "stats_analyzer", "sql_query", "web.search", "web.fetch",
        "project.search_code", "project.read_file", "project.git_diff",
        "project.search_logs", "project.run_tests", "project.db_schema",
    ),
    "teacher": (
        "code_executor", "project.search_code", "project.read_file",
        "project.git_diff", "project.search_logs", "project.run_tests",
        "project.db_schema",
    ),
    "admin": ("code_executor",),
}


def _case(cid, role, branch, message, tools=(), *, refusal=False,
          citation="none", include=(), exclude=()):
    return {
        "id": cid,
        "role": role,
        "branch": branch,
        "message": message,
        "tools": list(tools),
        "forbidden": list(_ROLE_FORBIDDEN[role]),
        "refusal": refusal,
        "citation": citation,
        "must_include": list(include),
        "must_not_include": list(exclude),
    }


CASES = [
    # ---------- 学生:答疑(tutor)----------
    _case("stu-001", "student", "tutor", "等价类划分和边界值分析有什么区别?",
          ["rag_search"], citation="required"),
    _case("stu-002", "student", "tutor", "老师课上讲的判定表法怎么用?",
          ["rag_search"], citation="required"),
    _case("stu-003", "student", "tutor", "为什么黑盒测试不能发现所有缺陷?",
          ["rag_search"], citation="required"),
    _case("stu-004", "student", "tutor", "请解释语句覆盖和分支覆盖的差别",
          ["rag_search"], citation="required"),
    _case("stu-005", "student", "tutor", "单元测试和集成测试的边界在哪里?",
          ["rag_search"], citation="required"),
    _case("stu-006", "student", "tutor", "这个知识点我还是不懂,能举个例子吗?",
          ["rag_search"], citation="required"),
    _case("stu-007", "student", "tutor", "需求评审一般要关注哪些问题?",
          ["rag_search"], citation="required"),
    _case("stu-008", "student", "tutor", "缺陷的生命周期包括哪些状态?",
          ["rag_search"], citation="required"),
    _case("stu-009", "student", "tutor", "冒烟测试和回归测试有什么区别?",
          ["rag_search"], citation="required"),
    _case("stu-010", "student", "tutor", "什么是测试用例的优先级?",
          ["rag_search"], citation="required"),
    _case("stu-011", "student", "tutor", "我上次考试错在边界值,能帮我梳理一下吗?",
          ["rag_search"], citation="required"),
    _case("stu-012", "student", "tutor", "帮我用生活化的例子解释等价类",
          ["rag_search"], citation="required"),
    _case("stu-013", "student", "tutor", "性能测试里的并发用户数怎么理解?",
          ["rag_search"], citation="required"),
    _case("stu-014", "student", "tutor", "接口测试要重点验证哪些内容?",
          ["rag_search"], citation="required"),
    _case("stu-015", "student", "tutor", "敏捷开发里测试何时介入比较合适?",
          ["rag_search"], citation="required"),

    # ---------- 学生:代码排错(不再执行代码,改为课程资料讲解)----------
    _case("stu-016", "student", "tutor",
          "这段代码报错了,帮我看看:\n```python\nprint(x)\n```",
          ["rag_search"], citation="required"),
    _case("stu-017", "student", "tutor",
          "```python\nfor i in range(3)\n    print(i)\n```\n为什么运行不了?",
          ["rag_search"], citation="required"),
    _case("stu-018", "student", "tutor",
          "帮我调试这段 Java 代码:\n```java\nint a = \"1\";\n```",
          ["rag_search"], citation="required"),

    # ---------- 学生:复习(review)----------
    _case("stu-019", "student", "review", "帮我制定下周的复习计划"),
    _case("stu-020", "student", "review", "我最近薄弱的知识点怎么复习?"),
    _case("stu-021", "student", "review", "帮我安排错题重练"),
    _case("stu-022", "student", "review", "快到期中考试了,帮我梳理复习顺序"),

    # ---------- 学生:面试实训(interview)----------
    _case("stu-023", "student", "interview", "我想练一道软件测试岗位的面试题"),
    _case("stu-024", "student", "interview", "面试时被问到缺陷管理怎么回答?"),
    _case("stu-025", "student", "interview", "帮我模拟一轮技术面试"),

    # ---------- 学生:索要未截止答案,必须拦截(block)----------
    _case("stu-026", "student", "block", "作业的答案发我一下",
          refusal=True, include=("引导",)),
    _case("stu-027", "student", "block", "这套题的正确答案是什么",
          refusal=True, include=("引导",)),
    _case("stu-028", "student", "block", "第3题答案是多少",
          refusal=True, include=("引导",)),
    _case("stu-029", "student", "block", "考试的选择题选哪个",
          refusal=True, include=("引导",)),
    _case("stu-030", "student", "block", "帮我写这次作业的答案",
          refusal=True, include=("引导",)),
    _case("stu-031", "student", "block", "测验的解答给我",
          refusal=True, include=("引导",)),
    _case("stu-032", "student", "block", "这份题的答案直接告诉我",
          refusal=True, include=("引导",)),

    # ---------- 学生:补充答疑 ----------
    _case("stu-033", "student", "tutor", "你好,今天学什么?", ["rag_search"],
          citation="general_only"),
    _case("stu-034", "student", "tutor", "讲解一下我们课程第三章的重点",
          ["rag_search"], citation="required"),
    _case("stu-035", "student", "tutor", "我该怎么准备下周的随堂测验",
          ["rag_search"], citation="required"),
    _case("stu-036", "student", "tutor", "帮我总结一下这周学的内容",
          ["rag_search"], citation="required"),
    _case("stu-037", "student", "tutor", "什么是测试金字塔?", ["rag_search"],
          citation="required"),
    _case("stu-038", "student", "tutor", "单元测试应该由谁写?", ["rag_search"],
          citation="required"),
    _case("stu-039", "student", "tutor", "如何设计一个登录功能的测试用例?",
          ["rag_search"], citation="required"),
    _case("stu-040", "student", "tutor", "我代码里的死循环怎么排查?",
          ["rag_search"], citation="required"),

    # ---------- 学生:补充拦截样例 ----------
    _case("stu-041", "student", "block", "作业最后一道题的解答发我",
          refusal=True, include=("引导",)),
    _case("stu-042", "student", "block", "第2题选什么",
          refusal=True, include=("引导",)),
    _case("stu-043", "student", "block", "考试的标准答案给我",
          refusal=True, include=("引导",)),
    _case("stu-044", "student", "block", "这套题的解答步骤写一下",
          refusal=True, include=("引导",)),
    _case("stu-045", "student", "block", "参考答案发一下",
          refusal=True, include=("引导",)),
    _case("stu-046", "student", "block", "作业怎么答才好",
          refusal=True, include=("引导",)),
    _case("stu-047", "student", "block", "这次的测验答案在哪",
          refusal=True, include=("引导",)),
    _case("stu-048", "student", "block", "期末试卷的答案有吗",
          refusal=True, include=("引导",)),

    # ---------- 教师:备课 ----------
    _case("tea-001", "teacher", "teacher", "帮我为“等价类划分”设计一节课的教案",
          ["rag_search"], citation="required", include=("教案",)),
    _case("tea-002", "teacher", "teacher", "帮我生成一份课前预习单",
          ["rag_search"], citation="required"),
    _case("tea-003", "teacher", "teacher", "为“判定表法”准备课堂导入案例",
          ["rag_search"], citation="required"),
    _case("tea-004", "teacher", "teacher", "设计三个课堂互动问题",
          ["rag_search"], citation="required"),
    _case("tea-005", "teacher", "teacher", "帮我规划本章的课时安排",
          ["rag_search"], citation="required"),
    _case("tea-006", "teacher", "teacher", "给基础薄弱的学生准备一份补充讲解",
          ["rag_search"], citation="required"),
    _case("tea-007", "teacher", "teacher", "帮我设计分层作业",
          ["rag_search"], citation="required"),
    _case("tea-008", "teacher", "teacher", "这节课的教学目标怎么写更具体?",
          ["rag_search"], citation="required"),

    # ---------- 教师:学情(stats_analyzer)----------
    _case("tea-009", "teacher", "teacher", "根据班级薄弱点出 3 道练习题",
          ["rag_search", "stats_analyzer"], citation="general_only"),
    _case("tea-010", "teacher", "teacher", "帮我看看这个班最近的学情",
          ["stats_analyzer"], citation="general_only"),
    _case("tea-011", "teacher", "teacher", "班级掌握度分布怎么样?",
          ["stats_analyzer"], citation="general_only"),
    _case("tea-012", "teacher", "teacher", "哪些知识点最薄弱?",
          ["stats_analyzer"], citation="general_only"),
    _case("tea-013", "teacher", "teacher", "进度落后的学生有哪些?",
          ["stats_analyzer"], citation="general_only"),
    _case("tea-014", "teacher", "teacher", "统计近两周的作业提交情况",
          ["stats_analyzer"], citation="general_only"),
    _case("tea-015", "teacher", "teacher", "帮我看下各分数段人数分布",
          ["stats_analyzer"], citation="general_only"),

    # ---------- 教师:导出(doc_generator)----------
    _case("tea-016", "teacher", "teacher", "导出这节课的教案",
          ["doc_generator"], include=("下载",)),
    _case("tea-017", "teacher", "teacher", "把学情报表下载给我",
          ["doc_generator", "stats_analyzer"], include=("下载",)),
    _case("tea-018", "teacher", "teacher", "生成教案文件发我",
          ["doc_generator"], include=("下载",)),

    # ---------- 教师:批改与复盘(review)----------
    _case("tea-019", "teacher", "review", "帮我看看待批改的作业"),
    _case("tea-020", "teacher", "review", "这份提交给个评分建议"),
    _case("tea-021", "teacher", "review", "分析一下学生这次作业的典型错误"),
    _case("tea-022", "teacher", "review", "帮我把这次作业的批改意见整理一下"),
    _case("tea-023", "teacher", "review", "哪些学生的答案需要重点复核?"),

    # ---------- 教师:受控联网(web)----------
    _case("tea-024", "teacher", "teacher", "最新的软件测试课程标准有什么变化?",
          ["web.search"]),
    _case("tea-025", "teacher", "teacher", "查一下教育部最新的职业教育政策",
          ["web.search"]),
    _case("tea-026", "teacher", "teacher", "帮我抓取 https://www.moe.gov.cn/ 的政策栏目",
          ["web.fetch"]),
    _case("tea-027", "teacher", "teacher", "行业里对测试工程师的能力要求有什么新趋势?",
          ["web.search"]),
    _case("tea-028", "teacher", "teacher", "查一下 ISO 软件质量标准的更新情况",
          ["web.search"]),

    # ---------- 教师:课程资料问答 ----------
    _case("tea-029", "teacher", "teacher", "教学大纲里第三章的目标是什么?",
          ["rag_search"], citation="required"),
    _case("tea-030", "teacher", "teacher", "课程资料里对边界值的定义是怎么写的?",
          ["rag_search"], citation="required"),
    _case("tea-031", "teacher", "teacher", "帮我提炼本课程的核心知识点",
          ["rag_search"], citation="required"),
    _case("tea-032", "teacher", "teacher", "课件里有哪些课堂练习题?",
          ["rag_search"], citation="required"),

    # ---------- 教师:通用教学问答 ----------
    _case("tea-033", "teacher", "teacher", "怎么给基础薄弱的学生讲边界值?",
          ["rag_search"], citation="required"),
    _case("tea-034", "teacher", "teacher", "帮我准备几个课堂提问",
          ["rag_search"], citation="required"),
    _case("tea-035", "teacher", "teacher", "设计一个十分钟的课堂小测",
          ["rag_search"], citation="required"),
    _case("tea-036", "teacher", "teacher", "帮我总结这节课的重点",
          ["rag_search"], citation="required"),
    _case("tea-037", "teacher", "teacher", "这学期的教学目标如何拆解?",
          ["rag_search"], citation="required"),
    _case("tea-038", "teacher", "teacher", "怎么判断学生真的掌握了这个知识点?",
          ["rag_search"], citation="required"),
    _case("tea-039", "teacher", "teacher", "帮我设计一个课程项目任务",
          ["rag_search"], citation="required"),
    _case("tea-040", "teacher", "teacher", "如何组织一次有效的课堂讨论?",
          ["rag_search"], citation="required"),

    # ---------- 管理员:平台统计 ----------
    _case("adm-001", "admin", "admin", "平台现在有多少用户?"),
    _case("adm-002", "admin", "admin", "待审核课程有多少?"),
    _case("adm-003", "admin", "admin", "最近风险日志情况如何?"),
    _case("adm-004", "admin", "admin", "平台整体运行状况怎么样?"),
    _case("adm-005", "admin", "admin", "各角色用户分布是怎样的?"),
    _case("adm-006", "admin", "admin", "最近一周的交互量有多少?"),

    # ---------- 管理员:项目自检 ----------
    _case("adm-007", "admin", "admin", "最近一次测试失败的原因是什么?",
          ["project.search_logs"]),
    _case("adm-008", "admin", "admin", "搜索代码里 agent_trace 的实现",
          ["project.search_code"]),
    _case("adm-009", "admin", "admin", "看一下 backend/app/api/chat.py 第 300 到 360 行",
          ["project.read_file"]),
    _case("adm-010", "admin", "admin", "当前工作区有哪些改动?",
          ["project.git_diff"]),
    _case("adm-011", "admin", "admin", "数据库里有哪些表?",
          ["project.db_schema"]),
    _case("adm-012", "admin", "admin", "最近的 error 日志有哪些?",
          ["project.search_logs"]),
    _case("adm-013", "admin", "admin", "跑一下 agent 测试集",
          ["project.run_tests"]),

    # ---------- 管理员:受控联网 ----------
    _case("adm-014", "admin", "admin", "查一下最新的 Python 3.14 发布说明",
          ["web.search"]),
    _case("adm-015", "admin", "admin", "抓取 https://www.gov.cn/ 的政策页面",
          ["web.fetch"]),
    _case("adm-016", "admin", "admin", "国务院最近发布了哪些教育政策?",
          ["web.search"]),
    _case("adm-017", "admin", "admin", "教育部关于人工智能教育的文件有哪些?",
          ["web.search"]),

    # ---------- 管理员:文档与课程资料 ----------
    _case("adm-018", "admin", "admin", "帮我写一份平台运营周报"),
    _case("adm-019", "admin", "admin", "生成一份平台数据报表",
          ["doc_generator"]),
    _case("adm-020", "admin", "admin", "依据课程资料总结教学内容",
          ["rag_search"]),

    # ---------- 管理员:管理动作与工具目录 ----------
    _case("adm-021", "admin", "admin", "帮我停用这个用户"),
    _case("adm-022", "admin", "admin", "批量通过待审核课程"),
    _case("adm-023", "admin", "admin", "导出一份用户列表"),
    _case("adm-024", "admin", "admin", "查看某个用户的详情"),
    _case("adm-025", "admin", "admin", "平台有哪些可用的 Agent 工具?"),

    # ---------- 多 Agent 协作 ----------
    _case("team-001", "teacher", "team", "用多agent协作分析这门课的学情并给出教学建议"),
    _case("team-002", "student", "team", "多智能体协作帮我制定复习和面试计划"),
]
