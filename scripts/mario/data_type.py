import pickle
# 找一个 shard
with open("dataset/random_data/stratified_rollouts_7000_qfirst_shards/episodes_shard_000001.pkl", "rb") as f:
    d = pickle.load(f)
ep = d["episodes"][0]
obs = ep["observations"]
print("type:", type(obs))
print("len:", len(obs))
print("单帧 shape:", obs[0].shape, "dtype:", obs[0].dtype)
print("单 episode 总大小(MB):", sum(o.nbytes for o in obs) / 1024 / 1024)

python -c "
import pickle, glob, os
shards = glob.glob('dataset/random_data/stratified_rollouts_7000_qfirst_shards/*.pkl')
with open(shards[0], 'rb') as f:
    d = pickle.load(f)
eps = d['episodes']
print('单 shard episode 数:', len(eps))
print('单 shard 总步数:', sum(len(e['actions']) for e in eps))
"