#!/usr/bin/env python3
"""
数据库初始化脚本
"""

import asyncio
import asyncpg
import sys
import os

async def init_database():
    """初始化数据库表结构"""
    try:
        print("正在连接到数据库...")

        # 从环境变量读取数据库连接配置
        db_host = os.environ.get('DB_HOST', 'localhost')
        db_port = int(os.environ.get('DB_PORT', '5432'))
        db_user = os.environ.get('DB_USER', 'ai_gateway')
        db_password = os.environ.get('DB_PASSWORD', '')
        db_name = os.environ.get('DB_NAME', 'ai_gateway')

        if not db_password:
            print("[ERROR] 请设置数据库密码环境变量: export DB_PASSWORD='your_password'")
            return False

        # 连接到数据库
        conn = await asyncpg.connect(
            user=db_user,
            password=db_password,
            host=db_host,
            port=db_port,
            database=db_name
        )
        
        print("[SUCCESS] 数据库连接成功")
        
        # 读取SQL文件
        print("正在读取初始化SQL脚本...")
        with open('init.sql', 'r', encoding='utf-8') as f:
            sql_content = f.read()
        
        # 分割SQL语句（按分号分割，但要注意函数定义中的分号）
        sql_statements = []
        current_statement = ""
        in_function = False
        in_quote = False
        quote_char = None
        
        for char in sql_content:
            current_statement += char
            
            # 处理引号
            if char in ("'", '"') and not in_quote:
                in_quote = True
                quote_char = char
            elif char == quote_char and in_quote:
                in_quote = False
                quote_char = None
            
            # 如果不是在引号内，检查分号
            elif char == ';' and not in_quote:
                sql_statements.append(current_statement.strip())
                current_statement = ""
        
        # 如果还有未添加的语句
        if current_statement.strip():
            sql_statements.append(current_statement.strip())
        
        print(f"找到 {len(sql_statements)} 条SQL语句")
        
        # 执行SQL语句
        success_count = 0
        fail_count = 0
        
        for i, sql in enumerate(sql_statements, 1):
            if not sql.strip() or sql.strip().startswith('--'):
                continue  # 跳过空行和注释
                
            print(f"执行语句 {i}/{len(sql_statements)}...")
            
            try:
                await conn.execute(sql)
                success_count += 1
                print(f"  语句 {i} 执行成功")
            except Exception as e:
                print(f"  语句 {i} 执行失败: {e}")
                fail_count += 1
        
        # 验证表创建
        print("\n验证表创建情况...")
        tables = await conn.fetch("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        
        print(f"数据库中的表 ({len(tables)} 张):")
        for table in tables:
            print(f"  - {table['table_name']}")
        
        await conn.close()
        
        print(f"\n初始化完成:")
        print(f"  成功: {success_count} 条语句")
        print(f"  失败: {fail_count} 条语句")
        
        if fail_count == 0:
            print("[SUCCESS] 数据库初始化成功！")
            return True
        else:
            print("[WARNING] 数据库初始化完成，但有部分语句失败")
            return True
            
    except Exception as e:
        print(f"[ERROR] 数据库初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # 运行初始化
    print("开始初始化AI大模型API网关数据库...")
    print("-" * 50)
    
    success = asyncio.run(init_database())
    
    print("-" * 50)
    if success:
        print("数据库初始化完成，可以启动应用了！")
        print("启动命令: python main.py")
        sys.exit(0)
    else:
        print("数据库初始化失败，请检查错误信息")
        sys.exit(1)