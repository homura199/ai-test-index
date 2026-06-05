import hashlib
import pandas as pd

# ==========================================
# 第一步：构建哈希反向查询表（彩虹表）
# 说明：通过穷举学号组合计算MD5，建立哈希值与原始信息的映射关系
# ==========================================
hash_mapping = {}

# 循环生成所有可能的学生标识组合
for cls_num in range(1, 3):                  # 班级：1、2
    cls = f"{cls_num}班"                     # 匹配前端选择的 "1班", "2班"
    for stu in range(1, 100):            # 学号：1～99号
        for ses in range(1, 10):         # 课次：1～9 (预留足够课次范围)
            # 匹配前端代码正确拼接的 `${cls}_${stu}_${ses}` 格式
            plain_text = f"{cls}_{stu}_{ses}"
            
            # 用MD5算法加密生成32位哈希值
            hash_val = hashlib.md5(plain_text.encode('utf-8')).hexdigest()
            
            # 将哈希值映射到原始明文，建立反向查询表
            hash_mapping[hash_val] = plain_text

print(f"✅ 映射表生成完成，共 {len(hash_mapping)} 条记录")


# ==========================================
# 第二步：数据清洗和反向解密
# 说明：读取包含聊天记录的CSV文件，将 user_id 列的反向解密成明文，并导出新文件
# ==========================================
input_file = "小智老师L2.csv"
output_file = "明文解密_小智老师L2.csv"

try:
    # 读取原始CSV数据
    df = pd.read_csv(input_file, encoding='gbk') # 尝试使用 'gbk' 编码读取，解决中文乱码问题
    
    # 检查是否存在 user_id 列
    if 'user_id' in df.columns:
        # 使用生成的哈希映射表，将 user_id 列解密。如果在彩虹表中找不到对应的MD5，则填充为"未知或外部人员"
        df['明文信息'] = df['user_id'].map(hash_mapping).fillna('未知或外部人员')
        
        # 调整列顺序：将"明文信息"移动到 user_id 列旁边，以便对照查看
        cols = list(df.columns)
        user_id_idx = cols.index('user_id')
        cols.insert(user_id_idx + 1, cols.pop(cols.index('明文信息')))
        df = df[cols]
        
        # 导出为新的CSV文件，使用 utf-8-sig 防止在 Excel 中打开时中文乱码
        df.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"✅ 处理成功！已将明文数据导出至同目录下的：{output_file}")
    else:
        print(f"❌ 错误：在文件 '{input_file}' 中未找到 'user_id' 列。")

except FileNotFoundError:
    print(f"❌ 错误：找不到文件 '{input_file}'，请确保 CSV 文件和该 Python 脚本放在同一个文件夹内。")
except Exception as e:
    print(f"❌ 处理过程中发生未知错误：{e}")