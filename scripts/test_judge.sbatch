#!/bin/bash
#SBATCH --job-name=hh-judge-test
#SBATCH --partition=testing
#SBATCH --gres=gpu:1
#SBATCH -c 4
#SBATCH --mem=48G
#SBATCH --time=01:00:00
#SBATCH --output=/extra/malmasik/house-hunt/logs/judge_test_%j.out
# Score the judge on the 24 hand-written posts, one model after another.
cd /extra/malmasik/house-hunt
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
/home/malmasik/.venvs/a100_new_real/bin/python scripts/test_judge.py \
  /extra/malmasik/hf_models/Qwen3.5-9B /extra/malmasik/hf_models/Qwen3.5-4B
