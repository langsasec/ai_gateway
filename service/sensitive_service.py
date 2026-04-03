"""
AI大模型API网关 - 敏感词检测服务
"""
import re
from typing import List, Optional, Tuple, Dict, Any
from datetime import datetime

from config import settings
from database import db


class SensitiveDetector:
    """敏感词检测器"""

    def __init__(self):
        # 每条记录: {"word": str, "type": str|None, "is_regex": bool, "compiled": re.Pattern}
        self.rules: List[Dict[str, Any]] = []
        self.initialized = False

    async def initialize(self):
        """初始化敏感词库（支持普通词 + 正则）"""
        try:
            rows = await db.fetch(
                "SELECT word, type, COALESCE(is_regex, FALSE) AS is_regex FROM sensitive_words"
            )

            rules = []
            for row in rows:
                word = row["word"]
                is_regex = bool(row["is_regex"])
                try:
                    pattern_str = word if is_regex else re.escape(word)
                    compiled = re.compile(pattern_str, re.IGNORECASE)
                    rules.append({
                        "word": word,
                        "type": row["type"],
                        "is_regex": is_regex,
                        "compiled": compiled
                    })
                except re.error as exc:
                    print(f"[敏感词] 正则编译失败 '{word}': {exc}")

            self.rules = rules
            # 保持向后兼容
            self.sensitive_words = [{"word": r["word"], "type": r["type"]} for r in rules]
            self.initialized = True
            print(f"敏感词检测器初始化完成，加载了 {len(self.rules)} 条规则 "
                  f"（正则: {sum(1 for r in rules if r['is_regex'])} 条）")
        except Exception as e:
            print(f"敏感词检测器初始化失败: {e}")
            self.initialized = False

    def detect_sensitive_content(self, text: str) -> Tuple[bool, Dict[str, Any]]:
        """
        检测敏感内容（同时支持普通词和正则）

        Returns:
            Tuple[found, detail]
            detail["words"]  每条命中记录 {"word":原始词/正则, "type":..., "is_regex":..., "matched": 实际命中的文本}
            detail["matched_patterns"] 命中词/正则字符串列表，供前端高亮
        """
        if not self.initialized:
            print(f"[敏感词] 检测器未初始化，跳过检测")
            return False, {"found": False, "words": [], "types": [], "matched_patterns": []}
        if not text:
            return False, {"found": False, "words": [], "types": [], "matched_patterns": []}

        detected_words = []
        detected_types = set()
        matched_patterns = []  # 命中的原始词/正则，供前端高亮

        for rule in self.rules:
            m = rule["compiled"].search(text)
            if m:
                entry = {
                    "word": rule["word"],
                    "type": rule["type"],
                    "is_regex": rule["is_regex"],
                    "matched": m.group(0)   # 实际命中的文本片段
                }
                detected_words.append(entry)
                detected_types.add(rule["type"])
                matched_patterns.append(rule["word"])

        found = len(detected_words) > 0
        return found, {
            "found": found,
            "words": detected_words,
            "types": list(detected_types),
            "matched_patterns": matched_patterns
        }
    
    def detect_personal_info(self, text: str) -> Dict[str, Any]:
        """
        检测个人敏感信息
        
        Args:
            text: 要检测的文本
            
        Returns:
            检测结果字典
        """
        results = {
            "id_card": False,
            "phone_number": False,
            "bank_card": False,
            "email": False
        }
        
        patterns = {
            "id_card": [
                r'\b[1-9]\d{5}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[0-9Xx]\b',  # 18位身份证
                r'\b[1-9]\d{7}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}\b'  # 15位身份证
            ],
            "phone_number": [
                r'\b1[3-9]\d{9}\b',  # 中国大陆手机号
                r'\b0\d{2,3}-?\d{7,8}\b'  # 固定电话
            ],
            "bank_card": [
                r'\b\d{16,19}\b'  # 银行卡号（16-19位数字）
            ],
            "email": [
                r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'  # 邮箱
            ]
        }
        
        for info_type, pattern_list in patterns.items():
            for pattern in pattern_list:
                if re.search(pattern, text):
                    results[info_type] = True
                    break
        
        # 检查是否有任何个人敏感信息
        results["has_personal_info"] = any(results.values())
        
        return results
    
    async def check_and_log_sensitive(self, 
                                     content: str, 
                                     request_id: str, 
                                     api_key: str,
                                     client_ip: str,
                                     content_type: str = "prompt") -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        检查敏感内容并记录日志
        
        Args:
            content: 内容文本
            request_id: 请求ID
            api_key: API密钥
            client_ip: 客户端IP
            content_type: 内容类型（prompt/response）
            
        Returns:
            Tuple[是否通过检查, 检测结果字典]
            - 拦截模式: found=True -> (False, result)
            - 审计模式: found=True -> (True, result)  不拦截但返回结果用于日志记录
            - 无命中:           -> (True, None)
        """
        try:
            # 检测敏感词
            has_sensitive_words, word_result = self.detect_sensitive_content(content)
            
            # 检测个人敏感信息
            personal_info_result = self.detect_personal_info(content)
            
            # 检查是否有任何命中
            has_issue = has_sensitive_words or personal_info_result["has_personal_info"]
            
            if not has_issue:
                return True, None
            
            # 调试日志
            print(f"[敏感词] 命中! content_type={content_type}, "
                  f"检测文本长度={len(content)}, "
                  f"敏感词命中={has_sensitive_words}, "
                  f"隐私信息命中={personal_info_result['has_personal_info']}")
            
            # 合并检测结果
            detection_result = {
                "timestamp": datetime.now().isoformat(),
                "content_type": content_type,
                "sensitive_words": word_result,
                "personal_info": personal_info_result,
                "action_taken": "none"
            }
            
            if settings.SENSITIVE_CHECK_MODE == "block":
                # 拦截模式
                detection_result["action_taken"] = "blocked"
                
                # 记录敏感内容日志
                await db.execute(
                    """
                    INSERT INTO request_logs
                    (request_id, api_key, client_ip, llm_name, prompt_content,
                     status, sensitive_result, error_msg)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    request_id,
                    api_key,
                    client_ip,
                    "sensitive_check",
                    content[:1000],  # 只存储前1000字符
                    "blocked",
                    str(detection_result),
                    "内容包含敏感信息，请求被拦截"
                )
                
                return False, detection_result
            else:
                # 审计模式：不拦截，但返回检测结果用于日志记录
                detection_result["action_taken"] = "audit_only"
                return True, detection_result
            
        except Exception as e:
            print(f"敏感内容检查失败: {e}")
            # 出现异常时默认通过检查
            return True, None
    
    async def add_sensitive_word(self, word: str, word_type: Optional[str] = None):
        """添加敏感词"""
        try:
            await db.execute(
                "INSERT INTO sensitive_words (word, type) VALUES ($1, $2) ON CONFLICT (word) DO NOTHING",
                word,
                word_type
            )
            
            # 重新初始化检测器
            await self.initialize()
            
            return True
        except Exception as e:
            print(f"添加敏感词失败: {e}")
            return False
    
    async def remove_sensitive_word(self, word: str):
        """删除敏感词"""
        try:
            await db.execute("DELETE FROM sensitive_words WHERE word = $1", word)
            
            # 重新初始化检测器
            await self.initialize()
            
            return True
        except Exception as e:
            print(f"删除敏感词失败: {e}")
            return False
    
    async def get_sensitive_words(self, word_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取敏感词列表"""
        try:
            if word_type:
                words = await db.fetch(
                    "SELECT id, word, type, create_time FROM sensitive_words WHERE type = $1 ORDER BY word",
                    word_type
                )
            else:
                words = await db.fetch(
                    "SELECT id, word, type, create_time FROM sensitive_words ORDER BY word"
                )
            
            return [dict(w) for w in words]
        except Exception as e:
            print(f"获取敏感词列表失败: {e}")
            return []


# 创建全局敏感词检测器实例
sensitive_detector = SensitiveDetector()