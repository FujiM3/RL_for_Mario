import pickle
import numpy as np
from collections import Counter
import os

def check_sharded_dataset():
    file_path = "dataset/random_data/stratified_rollouts_7000_qfirst.pkl"
    print(f"🔍 正在唤醒本管家的【终极碎片级】质检雷达，读取索引文件: {file_path} ...\n")
    
    try:
        with open(file_path, "rb") as f:
            data = pickle.load(f)
    except Exception as e:
        print(f"❌ 完蛋！索引文件读取失败！错误信息: {e}")
        return

    # 1. 揪出总目录里的所有碎片路径
    shard_files = data.get("shard_files", [])
    if not shard_files:
        print("❌ 气死我了！索引文件里连 shard_files 都找不到！你确定你跑到最后了吗？！")
        return

    print(f"📁 发现 {len(shard_files)} 个数据碎片(Shard)，正在逐个解包分析...")
    print(f"⏳ 数据量巨大，这可能需要一点时间，给本小姐耐心等着，不许催！\n")

    returns = []
    lengths = []
    clears = []
    levels = []

    # 2. 逐个解包碎片，汇总数据（这样不会撑爆你的内存！）
    for shard_path in shard_files:
        if not os.path.exists(shard_path):
            print(f"⚠️ 警告：找不到碎片文件 {shard_path}，是不是被你误删了？！")
            continue

        with open(shard_path, "rb") as f:
            shard_data = pickle.load(f)

        eps = shard_data.get("episodes", [])
        srcs = shard_data.get("episode_sources", [])

        # 榨干碎片里的每一滴价值
        returns.extend([float(np.sum(ep["rewards"])) for ep in eps])
        lengths.extend([int(len(ep["actions"])) for ep in eps])
        clears.extend([bool(np.any(ep["flag_gets"])) for ep in eps])
        levels.extend([src.get("level", "Unknown") for src in srcs])

    total_eps = len(returns)
    print(f"📊 【真正的基础容量】")
    print(f"总收集局数: **{total_eps}** 局 (这下该有几千局了吧？！)\n")
    
    if total_eps == 0:
        return

    print(f"📈 【得分与长度分布】(这是检验三梯队是否生效的核心！)")
    print(f"⭐ 分数 (Returns): 最高={np.max(returns):.2f}, 最低={np.min(returns):.2f}, 平均={np.mean(returns):.2f}")
    print(f"   (P90分数={np.percentile(returns, 90):.2f}, 中位数={np.median(returns):.2f})")
    print(f"⏳ 步数 (Lengths): 最长={np.max(lengths)}, 最短={np.min(lengths)}, 平均={np.mean(lengths):.2f}\n")
    
    print(f"🚩 【通关率 (Clear Rate)】")
    clear_rate = np.mean(clears) * 100
    print(f"整体通关率: {clear_rate:.2f}% (因为有微操自救和失败梯队，正常在 40% ~ 70% 之间)\n")

    if levels:
        print(f"🗺️ 【关卡多样性 (Level Distribution)】")
        level_counts = Counter(levels)
        print(f"覆盖了 {len(level_counts)} 个不同的关卡！")
        
        common_levels = level_counts.most_common()
        print("最常出现的5个关卡:")
        for lvl, count in common_levels[:5]:
            print(f"  - {lvl}: {count} 局")
            
        print("最少出现的5个关卡:")
        for lvl, count in common_levels[-5:]:
            print(f"  - {lvl}: {count} 局")

if __name__ == "__main__":
    check_sharded_dataset()