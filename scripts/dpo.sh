#!/bin/bash

#SBATCH --job-name=dpo    # Job name
#SBATCH --output=run_outputs/dpo.%j.out      # Name of output file (%j expands to jobId)
#SBATCH --cpus-per-task=12       # Schedule one core
#SBATCH --time=1-24:00:00          # Run time (hh:mm:ss) - run for one hour max
#SBATCH --gres=gpu:a100_80gb:1
#SBATCH --partition=brown,red    # Run on either the Red or Brown queue
#SBATCH --mail-type=BEGIN,FAIL,END    # Send an email when the job finishes or fails
#SBATCH --account=researchers

hostname

nvidia-smi

# module load poetry/1.5.1-GCCcore-12.3.0

# poetry shell

# poetry update

# poetry install

# pip install torch

python -m src.social_llama.training.dpo
