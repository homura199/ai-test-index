import hashlib
import pandas as pd

# ==========================================
# 1. 瞬间生成属于你的“彩虹表”字典
# ==========================================
hash_mapping = {}

# 遍历你前端所有可能的选项组合（假设：1-6班，1-99号，1-4课次）
for cls in range(1, 7):
    for stu in range(1, 100):
        for ses in range(1, 5):
            # 拼装当时前端传给云函数的原始明文格式
            plain_text = f"{cls}班_{stu}_{ses}"
            
            # 模拟后端的 MD5 加密过程 (生成 32位 字符串)
            # ⚠️ 注意：如果你后端代码里除了 md5 还加了“盐(salt)”，这里要保持一致
            hash_val = hashlib.md5(plain_text.encode('utf-8')).hexdigest()
            
            # 存入反向映射字典: { '哈希值': '明文' }
            hash_mapping[hash_val] = plain_text

print(f"✅ 成功生成映射字典，覆盖 {len(hash_mapping)} 种学号组合！")


# ==========================================
# 2. 模拟真实数据清洗流程
# ==========================================
# 假设你读取了扣子后台导出的 CSV 数据
# df = pd.read_csv('coze_exported_logs.csv')

# 【测试用的假数据】
data = {'coze_user_id': ['084e0343a0486ff05530df6c705c8bb4', 'c4ca4238a0b923820dcc509a6f75849b']} 
df = pd.DataFrame(data)

# 🚀 核心魔法：一键把哈希乱码全部映射回明文！
df['real_user_info'] = df['coze_user_id'].map(hash_mapping)

# 再顺手用下划线拆开，直接变成结构化的 3 列，完美对接后续的数据分析
df[['班级', '学号', '课次']] = df['real_user_info'].str.split('_', expand=True)

print("\n清洗后的数据：")
print(df)