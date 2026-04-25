import pickle
import os
from collections import Counter
import numpy as np

# 1. 再次读取这张“藏宝图”
data_path = 'dataset/random_data/stratified_rollouts_7000_qfirst.pkl'
with open(data_path, 'rb') as f:
    manifest = pickle.load(f)

# 2. 获取真正的碎片文件路径
shard_dir = manifest.get('shard_dir', '')
shard_files = manifest.get('shard_files', [])

if not shard_files:
    print("错误：连藏宝图里都没写宝藏在哪！")
    exit()

# 我们先抽查第一个碎片文件看看结构
first_shard_path = os.path.join(os.path.dirname(data_path), shard_files[0])
print(f"正在前往藏宝地点: {first_shard_path} ...")

with open(first_shard_path, 'rb') as f:
    shard_data = pickle.load(f)

# 3. 统计这一个碎片里的动作分布（管中窥豹）
all_actions = []
# 根据常见的碎片化存储格式进行遍历
target_list = shard_data if isinstance(shard_data, list) else shard_data.get('episodes', [])

for ep in target_list:
    if 'actions' in ep:
        all_actions.extend(ep['actions'])

all_actions = np.array(all_actions)
counts = Counter(all_actions)
total = len(all_actions)

print("\n--- 💎 碎片文件(0号)动作分布报告 ---")
print(f"该碎片内决策步数: {total}")

if total > 0:
    for act in range(7):
        count = counts.get(act, 0)
        percentage = (count / total) * 100
        print(f"动作 {act:2d}: {count:8d} 次 | 占比: {percentage:6.2f}%")
else:
    print("警告：连碎片里都是空的！这不科学！")