#!/bin/zsh
# Rerun e-012 on the model the other eleven cases used.
# In a file so the long --model argument cannot be split by a terminal line wrap,
# which is how this case ended up running on the wrong model the first time.
cd "/Users/shelbyprue/Desktop/AI Evals Course/cartwheel-homeworks"
exec .venv/bin/python scripts/run_baseline_local.py \
  --case e-012 -k 5 \
  --model openai/rl-muse-spark-1-1-playground
