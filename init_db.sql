-- ITEA-Agent 数据库初始化脚本
-- 基于 docs/设计方案.md 第三章

CREATE DATABASE IF NOT EXISTS itea_agent DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE itea_agent;

-- 1. users 用户表
CREATE TABLE IF NOT EXISTS users (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    role            ENUM('teacher','student','admin') NOT NULL,
    name            VARCHAR(50) NOT NULL,
    email           VARCHAR(100) NOT NULL UNIQUE,
    password_hash   VARCHAR(255) NOT NULL,
    status          ENUM('active','disabled') NOT NULL DEFAULT 'active' COMMENT '账号状态(管理端启停用)',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. courses 课程表
CREATE TABLE IF NOT EXISTS courses (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    teacher_id      BIGINT NOT NULL,
    name            VARCHAR(100) NOT NULL,
    code            VARCHAR(20) NOT NULL,
    syllabus        TEXT,
    semester        VARCHAR(20),
    audit_status    ENUM('pending','approved','rejected') NOT NULL DEFAULT 'approved' COMMENT '审核状态(补充字段,方案 courses 表未定义)',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (teacher_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. course_materials 课件素材表
CREATE TABLE IF NOT EXISTS course_materials (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    course_id       BIGINT NOT NULL,
    type            ENUM('courseware','syllabus','exercise','interview') NOT NULL,
    title           VARCHAR(200) NOT NULL,
    file_path       VARCHAR(500) NOT NULL,
    chunk_count     INT DEFAULT 0,
    uploaded_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4. knowledge_points 知识点表(树形结构)
CREATE TABLE IF NOT EXISTS knowledge_points (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    course_id       BIGINT NOT NULL,
    name            VARCHAR(100) NOT NULL,
    description     TEXT,
    parent_id       BIGINT DEFAULT NULL,
    FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_id) REFERENCES knowledge_points(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 5. student_profiles 学情档案表(全模块共享核心)
CREATE TABLE IF NOT EXISTS student_profiles (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id             BIGINT NOT NULL,
    course_id           BIGINT NOT NULL,
    overall_progress    DECIMAL(5,2) DEFAULT 0.00 COMMENT '总体进度(%)',
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_user_course (user_id, course_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 6. mastery_records 知识点掌握度表
CREATE TABLE IF NOT EXISTS mastery_records (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    profile_id          BIGINT NOT NULL,
    kp_id               BIGINT NOT NULL,
    mastery_level       INT DEFAULT 0 COMMENT '掌握度 0-100',
    last_assessed_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_profile_kp (profile_id, kp_id),
    FOREIGN KEY (profile_id) REFERENCES student_profiles(id) ON DELETE CASCADE,
    FOREIGN KEY (kp_id) REFERENCES knowledge_points(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 7. wrong_questions 错题集表
CREATE TABLE IF NOT EXISTS wrong_questions (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    profile_id          BIGINT NOT NULL,
    kp_id               BIGINT,
    question_content    TEXT NOT NULL,
    error_type          VARCHAR(50) COMMENT '错误类型(概念/逻辑/语法)',
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (profile_id) REFERENCES student_profiles(id) ON DELETE CASCADE,
    FOREIGN KEY (kp_id) REFERENCES knowledge_points(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 8. review_plans 复习计划表(遗忘曲线)
CREATE TABLE IF NOT EXISTS review_plans (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    wrong_question_id   BIGINT NOT NULL,
    next_review_at      DATETIME NOT NULL,
    review_count        INT DEFAULT 0,
    interval_days       INT DEFAULT 1,
    status              ENUM('pending','done','expired') DEFAULT 'pending',
    FOREIGN KEY (wrong_question_id) REFERENCES wrong_questions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 9. practice_records 练习记录表
CREATE TABLE IF NOT EXISTS practice_records (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    profile_id          BIGINT NOT NULL,
    kp_id               BIGINT,
    type                ENUM('in_class','variant','code') NOT NULL,
    content             TEXT NOT NULL,
    is_correct          BOOLEAN,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (profile_id) REFERENCES student_profiles(id) ON DELETE CASCADE,
    FOREIGN KEY (kp_id) REFERENCES knowledge_points(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 10. interview_records 面试记录表
CREATE TABLE IF NOT EXISTS interview_records (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    profile_id      BIGINT NOT NULL,
    round           INT NOT NULL,
    question        TEXT NOT NULL,
    answer          TEXT,
    score           INT,
    feedback        TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (profile_id) REFERENCES student_profiles(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 11. interaction_logs 交互日志表
CREATE TABLE IF NOT EXISTS interaction_logs (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id         BIGINT NOT NULL,
    session_id      VARCHAR(64) NOT NULL,
    role            VARCHAR(20),
    branch          VARCHAR(20),
    content         TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_session (user_id, session_id),
    INDEX idx_created (created_at),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 12. risk_logs 风控拦截日志表
CREATE TABLE IF NOT EXISTS risk_logs (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id         BIGINT NOT NULL,
    request_content TEXT NOT NULL,
    risk_type       VARCHAR(50) NOT NULL,
    action_taken    VARCHAR(50) NOT NULL,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_time (user_id, created_at),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 13. operation_logs 操作审计日志表(管理端专属)
CREATE TABLE IF NOT EXISTS operation_logs (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    admin_id        BIGINT NOT NULL,
    action          VARCHAR(50) NOT NULL COMMENT 'create/update/delete/disable/enable/approve/reject/config',
    target_type     VARCHAR(50) NOT NULL COMMENT 'user/course/material/config/risk_log',
    target_id       BIGINT DEFAULT NULL,
    detail          TEXT COMMENT '变更详情(含变更前后快照 JSON)',
    ip              VARCHAR(45),
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_admin_time (admin_id, created_at),
    FOREIGN KEY (admin_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 14. system_config 系统配置表(管理端专属)
CREATE TABLE IF NOT EXISTS system_config (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    config_key      VARCHAR(100) NOT NULL UNIQUE,
    config_value    TEXT,
    description     VARCHAR(200),
    updated_by      BIGINT DEFAULT NULL,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (updated_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 初始系统配置项
INSERT IGNORE INTO system_config (config_key, config_value, description) VALUES
('risk_guard_enabled', 'true', '前置语义风控总开关'),
('reflect_max_loops', '2', '反思校验最大循环次数'),
('rag_top_k', '5', '知识库检索返回片段数'),
('llm_model', '"deepseek-flash"', '当前使用的 LLM 模型');
