"""Generate reverse instructions for the socket benchmark."""

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed

import pandas as pd
from datasets import load_dataset
from openai import OpenAI
from torch.utils.data import DataLoader
from tqdm import tqdm

from social_llama.config import DATA_DIR_EVALUATION_SOCKET
from social_llama.config import DATA_DIR_REVERSE_INSTRUCTIONS
from social_llama.reverse_instructions.instruction_configs import (
    ReverseInstructionsPrompts,
)
from social_llama.reverse_instructions.utils import calculate_total_costs_from_nested
from social_llama.utils import save_json


# Get all the tasks
socket_prompts: pd.DataFrame = pd.read_csv(
    DATA_DIR_EVALUATION_SOCKET / "socket_prompts.csv"
)

# Get all classification tasks
start_index = 5  # Specify the start index
stop_index = 10  # Specify the stop index
cls_tasks = socket_prompts[socket_prompts["type"] == "CLS"][start_index:stop_index]

task_data = {}

for task in tqdm(cls_tasks["task"].unique(), desc="Load and sample data"):
    # Load the dataset for the task
    dataset = load_dataset(
        "Blablablab/SOCKET",
        task,
        trust_remote_code=True,
        num_proc=8,
    )

    # Remove the sockette split
    if "sockette" in dataset:
        del dataset["sockette"]

    select_size = 4000

    # Sample 2000 examples from the 'train' split of the dataset
    if len(dataset["train"]) > select_size:
        dataset["train"] = dataset["train"].shuffle(seed=42).select(range(select_size))

    # Sample 10% of the 'train' split size from the other splits
    sample_size = len(dataset["train"]) // 10
    for split in dataset.keys():
        if split != "train" and len(dataset[split]) > sample_size:
            dataset[split] = dataset[split].shuffle(seed=42).select(range(sample_size))

    # Store the dataset in the dictionary
    task_data[task] = dataset

# Generate the reverse instructions

# Initialize the reverse instructions prompts
(
    system_prompt,
    reverse_instructions_prompts,
) = ReverseInstructionsPrompts().reverse_instruction_cls()

client = OpenAI()


# Function to process each sample
def process_sample(
    sample, labels_mapping, labels, system_prompt, reverse_instructions_prompts, client
):
    """Process each sample to generate reverse instructions."""
    text = sample["text"][0]
    label = labels_mapping[sample["label"].item()]

    sample_reverse_instruction_prompt = reverse_instructions_prompts.format(
        text=text, label_list=labels, label=label
    )

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo-0125",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": sample_reverse_instruction_prompt},
            ],
        )
    except Exception as e:
        return {
            "text": text,
            "label": label,
            "prompt": sample_reverse_instruction_prompt,
            "reverse_instruction": f"Failed. Error: {e}",
            "metadata": {"created": "", "model": "", "usage": {"completion_tokens": 0}},
        }

    return {
        "text": text,
        "label": label,
        "prompt": sample_reverse_instruction_prompt,
        "reverse_instruction": response.choices[0].message.content,
        "metadata": {
            "created": response.created,
            "model": response.model,
            "usage": response.usage.__dict__,
        },
    }


for task, dataset in tqdm(
    task_data.items(),
    desc="Generate reverse instructions",
    total=len(task_data),
    unit="task:",
):
    task_data_reverse_instructions = {}

    for split, data in tqdm(dataset.items(), desc=f"Task: {task}", unit="split"):
        labels = data.features["label"].names
        labels_mapping = {i: label for i, label in enumerate(labels)}

        with ThreadPoolExecutor(
            max_workers=30
        ) as executor:  # Adjust max_workers based on your environment
            future_to_sample = {
                executor.submit(
                    process_sample,
                    sample,
                    labels_mapping,
                    labels,
                    system_prompt,
                    reverse_instructions_prompts,
                    client,
                ): sample
                for sample in DataLoader(data, batch_size=1)
            }

            for future in tqdm(
                as_completed(future_to_sample),
                total=len(future_to_sample),
                desc=f"Processing {split}",
            ):
                sample_output = future.result()
                task_data_reverse_instructions.setdefault(split, []).append(
                    sample_output
                )

    price_per_million_completion_tokens = 1.5
    price_per_million_prompt_tokens = 0.5

    generation_costs = calculate_total_costs_from_nested(
        [task_data_reverse_instructions],
        price_per_million_completion_tokens=price_per_million_completion_tokens,
        price_per_million_prompt_tokens=price_per_million_prompt_tokens,
    )

    task_data_reverse_instructions["generation_costs"] = generation_costs

    save_json(
        DATA_DIR_REVERSE_INSTRUCTIONS / f"{task}_reverse_instructions.json",
        [task_data_reverse_instructions],
    )
