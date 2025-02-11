#!/bin/bash

#SBATCH --job-name=classifier    # Job name
#SBATCH --output=run_outputs/classifier.%j.out      # Name of output file (%j expands to jobId)
#SBATCH --cpus-per-task=20       # Schedule one core
#SBATCH --time=16:00:00          # Run time (hh:mm:ss) - run for one hour max
#SBATCH --gres=gpu:a100_40gb:1
#SBATCH --partition=brown,red    # Run on either the Red or Brown queue
#SBATCH --mail-type=BEGIN,FAIL,END    # Send an email when the job finishes or fails
#SBATCH --account=researchers

hostname

nvidia-smi

python -m src.social_llama.training.classification
