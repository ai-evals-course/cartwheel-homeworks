#!/bin/zsh
# Run the Part D CI subset. In a file because the long --model argument has been
# split by terminal line wrapping three times, once sending a whole case to the
# wrong model.
#
# Subset rather than all 12 cases: at the endpoint's current speed two full runs
# would be ~120 agent runs and most of a day. These three exercise every branch of
# the gate -- a regression that must block when broken, a regression that must stay
# green, and a capability that must never block.
cd "/Users/shelbyprue/Desktop/AI Evals Course/cartwheel-homeworks"
exec .venv/bin/python scripts/run_ci_local.py \
  --job-name "${1:?pass a job name, e.g. hw6-evals-regression}" \
  --case e-007 --case e-010 --case e-009 \
  --n-attempts 5 \
  --model openai/rl-muse-spark-1-1-playground
