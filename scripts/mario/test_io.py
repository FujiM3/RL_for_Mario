import os
import sys

import torch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from envs.mario_env import MarioEnvWrapper
from model.model_decision_transformer import DecisionTransformerConfig, MarioDecisionTransformer


def main():
    env = MarioEnvWrapper(frame_stack=4, resize_shape=(84, 84), grayscale=True, frame_skip=4)
    obs, info = env.reset(seed=42)

    cfg = DecisionTransformerConfig(
        state_shape=tuple(obs.shape),
        act_dim=env.action_space.n,
        context_len=8,
        hidden_size=256,
        num_hidden_layers=4,
        num_attention_heads=8,
        num_key_value_heads=2,
        use_moe=False,
    )
    model = MarioDecisionTransformer(cfg).eval()

    B = 1
    T = 4
    states = torch.zeros((B, T, *cfg.state_shape), dtype=torch.uint8)
    actions = torch.zeros((B, T), dtype=torch.long)
    returns_to_go = torch.zeros((B, T), dtype=torch.float32)
    timesteps = torch.arange(T, dtype=torch.long).unsqueeze(0)
    attention_mask = torch.ones((B, T), dtype=torch.long)

    states[0, -1] = torch.from_numpy(obs)
    with torch.no_grad():
        outputs = model(
            states=states,
            actions=actions,
            returns_to_go=returns_to_go,
            timesteps=timesteps,
            attention_mask=attention_mask,
        )
    assert outputs.action_logits.shape == (B, T, cfg.act_dim), outputs.action_logits.shape
    assert outputs.value_preds.shape == (B, T), outputs.value_preds.shape

    action = model.act(
        states=states,
        actions=actions,
        returns_to_go=returns_to_go,
        timesteps=timesteps,
        attention_mask=attention_mask,
        deterministic=False,
    )
    assert action.shape == (B,), action.shape
    env_action = int(action.item())
    step_out = env.step(env_action)
    assert len(step_out) == 5, len(step_out)
    next_obs, reward, terminated, truncated, _ = step_out
    assert next_obs.shape == cfg.state_shape, (next_obs.shape, cfg.state_shape)
    print("PASS", outputs.action_logits.shape, outputs.value_preds.shape, next_obs.shape, reward, terminated, truncated)
    env.close()


if __name__ == "__main__":
    main()
