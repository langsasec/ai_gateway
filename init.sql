-- AI大模型API网关 - 数据库初始化脚本
-- 与线上数据库结构完全一致

-- =============================================
-- 表结构
-- =============================================

-- 管理员表
CREATE TABLE IF NOT EXISTS admin (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    create_time TIMESTAMP DEFAULT NOW()
);

-- 大模型配置表
CREATE TABLE IF NOT EXISTS llm_config (
    id SERIAL PRIMARY KEY,
    llm_name VARCHAR(50) NOT NULL,
    api_url VARCHAR(255) NOT NULL,
    api_key VARCHAR(255) NOT NULL,
    status INT DEFAULT 1,
    create_time TIMESTAMP DEFAULT NOW()
);

-- API密钥表
CREATE TABLE IF NOT EXISTS api_key (
    id SERIAL PRIMARY KEY,
    key_value VARCHAR(100) NOT NULL UNIQUE,
    user_name VARCHAR(50),
    llm_ids INT[],
    rate_limit INT DEFAULT 10,
    daily_limit INT DEFAULT 1000,
    monthly_limit INT DEFAULT 30000,
    expire_time TIMESTAMP,
    ip_whitelist TEXT[],
    status INT DEFAULT 1,
    create_time TIMESTAMP DEFAULT NOW(),
    last_use_time TIMESTAMP,
    total_requests INT DEFAULT 0,
    daily_requests INT DEFAULT 0,
    monthly_requests INT DEFAULT 0,
    token_limit BIGINT DEFAULT 0,
    total_tokens BIGINT DEFAULT 0
);

-- 敏感词表
CREATE TABLE IF NOT EXISTS sensitive_words (
    id SERIAL PRIMARY KEY,
    word VARCHAR(500) NOT NULL UNIQUE,
    type VARCHAR(20),
    create_time TIMESTAMP DEFAULT NOW(),
    is_regex BOOLEAN DEFAULT FALSE,
    is_preset BOOLEAN DEFAULT FALSE
);

-- 敏感词检测配置表
CREATE TABLE IF NOT EXISTS sensitive_config (
    id SERIAL PRIMARY KEY,
    mode VARCHAR(10) DEFAULT 'audit',
    check_request BOOLEAN DEFAULT TRUE,
    check_response BOOLEAN DEFAULT TRUE,
    enable_pii_detection BOOLEAN DEFAULT TRUE,
    updated_time TIMESTAMP DEFAULT NOW()
);

-- 请求日志表
CREATE TABLE IF NOT EXISTS request_logs (
    id SERIAL PRIMARY KEY,
    request_id VARCHAR(36) NOT NULL UNIQUE DEFAULT gen_random_uuid()::text,
    api_key VARCHAR(100) NOT NULL,
    user_name VARCHAR(50),
    request_time TIMESTAMP DEFAULT NOW(),
    client_ip VARCHAR(50),
    llm_name VARCHAR(50),
    prompt_content TEXT,
    image_content TEXT,
    response_content TEXT,
    prompt_tokens INT,
    completion_tokens INT,
    status VARCHAR(20),
    sensitive_result TEXT,
    error_msg TEXT
);

-- 系统配置表
CREATE TABLE IF NOT EXISTS system_config (
    id SERIAL PRIMARY KEY,
    config_key VARCHAR(50) NOT NULL UNIQUE,
    config_value TEXT,
    description TEXT,
    updated_time TIMESTAMP DEFAULT NOW()
);

-- =============================================
-- 索引
-- =============================================

CREATE INDEX IF NOT EXISTS idx_api_key_status ON api_key(status);
CREATE INDEX IF NOT EXISTS idx_api_key_expire_time ON api_key(expire_time);
CREATE INDEX IF NOT EXISTS idx_sensitive_words_type ON sensitive_words(type);
CREATE INDEX IF NOT EXISTS idx_request_logs_api_key ON request_logs(api_key);
CREATE INDEX IF NOT EXISTS idx_request_logs_request_time ON request_logs(request_time);
CREATE INDEX IF NOT EXISTS idx_request_logs_status ON request_logs(status);
CREATE INDEX IF NOT EXISTS idx_request_logs_llm_name ON request_logs(llm_name);
CREATE INDEX IF NOT EXISTS idx_request_logs_time ON request_logs(request_time DESC);

-- =============================================
-- 初始数据
-- =============================================

-- 插入默认管理员账号（密码：admin123）
INSERT INTO admin (username, password) 
VALUES ('admin', '$2b$12$2AavT5opy1FneTlScqImY.q0sh5Ne4jJbqsN50FtckyfM85JpAx4.')
ON CONFLICT (username) DO NOTHING;

-- 插入默认系统配置
INSERT INTO system_config (config_key, config_value, description) VALUES
('app_name', 'AI大模型API网关', '应用名称'),
('app_version', '1.0.0', '应用版本'),
('max_request_size', '10485760', '最大请求大小（10MB）'),
('max_response_size', '10485760', '最大响应大小（10MB）'),
('default_rate_limit', '10', '默认请求频率限制（QPS）'),
('default_daily_limit', '1000', '默认日调用限制'),
('log_retention_days', '90', '日志保留天数'),
('enable_ip_whitelist', 'false', '是否启用IP白名单')
ON CONFLICT (config_key) DO UPDATE 
SET config_value = EXCLUDED.config_value;

-- 插入默认敏感词检测配置
INSERT INTO sensitive_config (mode, check_request, check_response, enable_pii_detection) 
VALUES ('audit', TRUE, TRUE, TRUE)
ON CONFLICT (id) DO NOTHING;

-- =============================================
-- 预置敏感词和正则规则
-- =============================================

-- 普通敏感词
INSERT INTO sensitive_words (word, type, is_regex) VALUES
('敏感词1', 'general', FALSE),
('敏感词2', 'general', FALSE),
('敏感词3', 'general', FALSE)
ON CONFLICT (word) DO NOTHING;

-- 身份证件类正则
INSERT INTO sensitive_words (word, type, is_regex, is_preset) VALUES
('[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]', '身份证', TRUE, TRUE),
('[1-9]\d{7}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}', '身份证', TRUE, TRUE),
('[A-Z]{1,2}\d{6}\(?[0-9A]\)?', '身份证', TRUE, TRUE),
('[A-Z]\d{9}', '身份证', TRUE, TRUE),
('[157]\d{6}\(?\d{3}\)?', '身份证', TRUE, TRUE),
('[A-Z]\d{8}', '护照号码', TRUE, TRUE),
('E\d{8}', '护照号码', TRUE, TRUE),
('军字第\d{6,8}号', '军官证', TRUE, TRUE),
('兵字第\d{6,8}号', '士兵证', TRUE, TRUE)
ON CONFLICT (word) DO NOTHING;

-- 银行金融类正则
INSERT INTO sensitive_words (word, type, is_regex, is_preset) VALUES
('\b(?:62|45|35|37|40|41|42|43|44|49|50|51|52|53|54|55|56|58|60|64|65|68|81|82|84|91)\d{14,17}\b', '银行卡号', TRUE, TRUE),
('\b4\d{15}\b', '银行卡号_Visa', TRUE, TRUE),
('\b5[1-5]\d{14}\b', '银行卡号_MasterCard', TRUE, TRUE),
('\b3[47]\d{13}\b', '银行卡号_AmEx', TRUE, TRUE),
('(?:CVV|CVC|CVN)\s*[:：]?\s*\d{3,4}', '银行卡CVV', TRUE, TRUE),
('(?:0[1-9]|1[0-2])\/\d{2}', '银行卡有效期', TRUE, TRUE),
('[A-Z]{4}C[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?', 'SWIFT代码', TRUE, TRUE)
ON CONFLICT (word) DO NOTHING;

-- 通信信息类正则
INSERT INTO sensitive_words (word, type, is_regex, is_preset) VALUES
('\b1[3-9]\d{9}\b', '手机号', TRUE, TRUE),
('\+?86\s*1[3-9]\d{9}', '手机号_国际', TRUE, TRUE),
('\b1[3-9]\d[\s-]?\d{4}[\s-]?\d{4}', '手机号_分隔', TRUE, TRUE),
('\b0\d{2,3}[-]?\d{7,8}\b', '固定电话', TRUE, TRUE),
('\+\d{1,3}[-\s]?\(?\d{2,4}\)?[-\s]?\d{4,9}', '国际电话', TRUE, TRUE),
('[48]00[-\s]?\d{3}[-\s]?\d{4}', '客服电话', TRUE, TRUE)
ON CONFLICT (word) DO NOTHING;

-- 网络信息类正则
INSERT INTO sensitive_words (word, type, is_regex, is_preset) VALUES
('(?:(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)', 'IP地址', TRUE, TRUE),
('(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}', 'IPv6地址', TRUE, TRUE),
('(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', 'MAC地址', TRUE, TRUE),
('(?:[0-9A-Fa-f]{2}-){5}[0-9A-Fa-f]{2}', 'MAC地址', TRUE, TRUE),
('https?://[^\s<>"'']+', 'URL网址', TRUE, TRUE)
ON CONFLICT (word) DO NOTHING;

-- 邮箱
INSERT INTO sensitive_words (word, type, is_regex, is_preset) VALUES
('[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}', '电子邮件', TRUE, TRUE)
ON CONFLICT (word) DO NOTHING;

-- 车辆信息类正则
INSERT INTO sensitive_words (word, type, is_regex, is_preset) VALUES
('[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤川青藏琼宁][A-HJ-NP-Z][A-HJ-NP-Z0-9]{4,5}[A-HJ-NP-Z0-9挂学警港澳]', '车牌号', TRUE, TRUE),
('[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤川青藏琼宁][A-HJ-NP-Z][0-9]{6}', '车牌号_新能源', TRUE, TRUE),
('[A-HJ-NPR-Z0-9]{17}', '车辆VIN码', TRUE, TRUE)
ON CONFLICT (word) DO NOTHING;

-- 地址信息类正则
INSERT INTO sensitive_words (word, type, is_regex, is_preset) VALUES
('[1-9]\d{5}(?!\d)', '邮政编码', TRUE, TRUE)
ON CONFLICT (word) DO NOTHING;

-- 账号凭证类正则
INSERT INTO sensitive_words (word, type, is_regex, is_preset) VALUES
('(?:password|passwd|pwd)\s*[=:]\s*[^\s''";,}\]]{4,}', '密码泄露', TRUE, TRUE),
('(?:api[_\-]?key|apikey|access[_\-]?key|secret[_\-]?key)\s*[=:]\s*[^\s''";,}\]]{8,}', 'API密钥泄露', TRUE, TRUE),
('(?:token|bearer|auth)\s*[=:]\s*[^\s''";,}\]]{8,}', 'Token泄露', TRUE, TRUE),
('Bearer\s+[A-Za-z0-9\-._~+/]+=*', 'Bearer_Token', TRUE, TRUE),
('(?:mysql|postgresql|postgres|mongodb|redis|sqlite)://[^\s''";,}\]]+', '数据库连接串', TRUE, TRUE),
('AKIA[0-9A-Z]{16}', 'AWS_AccessKey', TRUE, TRUE),
('eyJ[A-Za-z0-9\-._]+\.eyJ[A-Za-z0-9\-._]+\.[A-Za-z0-9\-._]+', 'JWT_Token', TRUE, TRUE)
ON CONFLICT (word) DO NOTHING;

-- 社交账号类正则
INSERT INTO sensitive_words (word, type, is_regex, is_preset) VALUES
('微信号\s*[：:]\s*[a-zA-Z0-9_]{6,20}', '微信号', TRUE, TRUE),
('QQ\s*[：:]\s*[1-9]\d{4,11}', 'QQ号', TRUE, TRUE)
ON CONFLICT (word) DO NOTHING;

-- 企业信息类正则
INSERT INTO sensitive_words (word, type, is_regex, is_preset) VALUES
('[0-9A-HJ-NP-RTUW-Y]{2}\d{6}[0-9A-HJ-NP-RTUW-Y]{10}', '统一社会信用代码', TRUE, TRUE)
ON CONFLICT (word) DO NOTHING;

-- 安全攻击类正则
INSERT INTO sensitive_words (word, type, is_regex, is_preset) VALUES
('UNION\s+(?:ALL\s+)?SELECT', 'SQL注入', TRUE, TRUE),
('OR\s+[''"]?\d+[''"]?\s*=\s*[''"]?\d+', 'SQL注入', TRUE, TRUE),
('(?:--\s|/\*|\*/|;\s*DROP|;\s*DELETE|;\s*UPDATE|;\s*INSERT|;\s*ALTER)', 'SQL注入', TRUE, TRUE),
('(?:SLEEP\s*\(|BENCHMARK\s*\(|WAITFOR\s+DELAY)', 'SQL注入', TRUE, TRUE),
('<\s*script[\s>]|javascript\s*:', 'XSS攻击', TRUE, TRUE),
('on(?:error|load|click|mouseover|focus|blur)\s*=', 'XSS攻击', TRUE, TRUE),
('\.\./|\.\.\\|%2e%2e', '路径遍历', TRUE, TRUE)
ON CONFLICT (word) DO NOTHING;

-- 医疗信息类正则
INSERT INTO sensitive_words (word, type, is_regex, is_preset) VALUES
('(?:BL|bl|病案|病历)\s*[-:]?\s*\d{6,12}', '病历号', TRUE, TRUE),
('(?:ZY|zy|住院)\s*[-:]?\s*\d{6,12}', '住院号', TRUE, TRUE)
ON CONFLICT (word) DO NOTHING;

-- 旅行信息类正则
INSERT INTO sensitive_words (word, type, is_regex, is_preset) VALUES
('(?:CA|MU|CZ|HU|ZH|3U|FM|9C|SC|MF|GS|KN|EU|G5|8L)\d{3,4}', '航班号', TRUE, TRUE),
('(?:G|D|C|K|T|Z|Y)\d{1,4}(?:次)?', '火车车次', TRUE, TRUE),
('(?:SF|JD|YT|ZTO|YTO|STO|DBL|EMS)\d{10,20}', '快递单号', TRUE, TRUE)
ON CONFLICT (word) DO NOTHING;
