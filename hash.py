import hashlib
import pandas as pd

# ==========================================
# 第一步：构建哈希反向查询表（彩虹表）
# 说明：通过穷举学号组合计算MD5，建立哈希值与原始信息的映射关系
#      用于后续数据解密
# ==========================================
hash_mapping = {}

# 三层循环生成所有可能的学生标识组合
for cls in range(1, 7):                  # 班级：1班～6班
    for stu in range(1, 100):            # 学号：1～99号
        for ses in range(1, 5):          # 课次：1～4课次
            # 构建学生身份字符串（未加密的原始明文）
            plain_text = f"{cls}班_{stu}_{ses}"
            
            # 用MD5算法加密生成32位哈希值
            # 注意：如果后端添加了盐值(salt)，这里需要保持一致！
            hash_val = hashlib.md5(plain_text.encode('utf-8')).hexdigest()
            
            # 将哈希值映射到原始明文，建立反向查询表
            # 这样可以通过哈希值还原出真实的学生信息
            hash_mapping[hash_val] = plain_text

# 显示生成结果
print(f"✅ 映射表生成完成，共 {len(hash_mapping)} 条记录")


# ==========================================
# 第二步：数据清洗和反向解密
# 说明：读取API导出的日志数据，将加密的用户ID还原为原始信息
# ==========================================
# 实际使用时应该从文件读取：df = pd.read_csv('coze_exported_logs.csv')

# 模拟从Coze后台导出的数据（包含加密的用户ID）
data = {'coze_user_id': ['bf0658374779eda2819acd4d40961c50']} 
df = pd.DataFrame(data)

# 核心步骤：用前面构建的映射表将加密的哈希值转换回明文
df['real_user_info'] = df['coze_user_id'].map(hash_mapping)

# 将原始信息按照下划线分割，得到结构化的数据列
# 便于后续进行学号、班级等维度的统计分析
df[['班级', '学号', '课次']] = df['real_user_info'].str.split('_', expand=True)

print("\n✓ 数据清洗完成，结果如下：")
print(df)