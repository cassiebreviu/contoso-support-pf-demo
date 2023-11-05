#!/bin/bash

# Get the current directory name
current_dir=${PWD##*/}

# Check if the current directory is not 'support-retail-copilot'
if [ "$current_dir" != "support-retail-copilot" ]; then
    echo "You are not in the 'support-retail-copilot' directory."
    echo "Please change to that folder and run this script with 'sh scripts/exp.sh'"
    exit 1
fi

# create a name for the run
run_name=run_$(date +%Y%m%d_%H%M%S)
echo "run name: $run_name"
# create the run
pfazure run create -f scripts/yaml/rag_job.yaml --name $run_name --stream
# evaluate the run
pfazure run create -f scripts/yaml/eval_job.yaml --run $run_name --stream --name quick_eval_2