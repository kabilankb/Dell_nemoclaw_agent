# Policy Tuning — `policies/`

The single front door to isaac-claw's policy hyperparameter "control panel".
These Markdown files are written to be read by both humans and local models
(Gemma, Nemotron): each per-framework file exposes ONE canonical fenced
` ```yaml ` block of tunable knobs that a launcher parses and applies.

**Start here →** [`policy_skill.md`](policy_skill.md) — the master router. It
maps each framework to its file, explains the read-the-block → edit-whitelisted-
knobs → hand-to-launcher loop, and holds the cross-framework glossary of
universal knobs (learning_rate, gamma, lambda/GAE, entropy, clip, num_envs,
max_iterations, seed, minibatch, horizon).

## Framework files

| File | Covers |
|------|--------|
| [`rsl_rl.md`](rsl_rl.md) | RSL-RL + CusRL PPO — default Robot Lab locomotion (XBot, G1, H1, quadrupeds). Repo-verified PPO config and reward weights. |
| [`rl_games.md`](rl_games.md) | rl_games PPO/SAC — Isaac Lab standard high-throughput backend. |
| [`skrl.md`](skrl.md) | skrl PPO / **AMP** (G1 dance) / IPPO / MAPPO — present in this checkout. |
| [`sb3.md`](sb3.md) | Stable-Baselines3 PPO/SAC — quick baselines and sanity checks. |
| [`robomimic.md`](robomimic.md) | Imitation learning — robomimic BC / BC-RNN, plus LeRobot ACT / diffusion knobs used by the leisaac mimic pipeline. |

Values are mined from the repo's own references and training scripts; any
value taken from a framework's published defaults rather than verified in this
repo is labelled **[framework-default]**.
