#!/bin/bash
#SBATCH --job-name=hh-judge-cpu
#SBATCH --partition=allgroups
#SBATCH -c 8
#SBATCH --mem=32G
#SBATCH --time=01:30:00
#SBATCH --output=/extra/malmasik/house-hunt/logs/judge_cpu_%j.out
# Is Qwen3.5-4B fast enough on CPU alone to judge a few posts an hour?
cd /extra/malmasik/house-hunt
lscpu | grep -E "Model name|^CPU\(s\)|avx512_bf16|amx" | head -3
export OMP_NUM_THREADS=8
/home/malmasik/.venvs/a100_new_real/bin/python scripts/test_judge.py /extra/malmasik/hf_models/Qwen3.5-4B
