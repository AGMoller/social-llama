"""Merge base model with adapter model."""

from dataclasses import dataclass
from dataclasses import field
from typing import Optional

import torch
from peft import PeftConfig
from peft import PeftModel
from transformers import AutoModelForCausalLM
from transformers import AutoModelForSequenceClassification
from transformers import AutoTokenizer
from transformers import HfArgumentParser


@dataclass
class ScriptArguments:
    """The name of the Casual LM model we wish to fine with PPO."""

    adapter_model_name: Optional[str] = field(
        # default="dpo/Llama-2-7b-chat-hf_zero-shot_combined_3epoch/final_checkpoint/",
        default="dpo/Meta-Llama-3-8B-Instruct_socket_1_epoch_1_epoch/final_checkpoint/",
        metadata={"help": "the model name"},
    )
    base_model_name: Optional[str] = field(
        default="meta-llama/Meta-Llama-3-8B-Instruct",
        metadata={"help": "the model name"},
    )
    output_name: Optional[str] = field(
        default="social-llama-3-8b-beta", metadata={"help": "the model name"}
    )


parser = HfArgumentParser(ScriptArguments)
script_args = parser.parse_args_into_dataclasses()[0]

peft_config = PeftConfig.from_pretrained(script_args.adapter_model_name)
if peft_config.task_type == "SEQ_CLS":
    # peft is for reward model so load sequence classification
    model = AutoModelForSequenceClassification.from_pretrained(
        script_args.base_model_name, num_labels=1, torch_dtype=torch.bfloat16
    )
else:
    model = AutoModelForCausalLM.from_pretrained(
        script_args.base_model_name, return_dict=True, torch_dtype=torch.bfloat16
    )

tokenizer = AutoTokenizer.from_pretrained(script_args.base_model_name)

# Load the Lora model
model = PeftModel.from_pretrained(model, script_args.adapter_model_name)
model.eval()

model = model.merge_and_unload()

model.save_pretrained(f"{script_args.output_name}")
tokenizer.save_pretrained(f"{script_args.output_name}")
model.push_to_hub(f"{script_args.output_name}", use_temp_dir=False)

tokenizer.push_to_hub(f"{script_args.output_name}", use_temp_dir=False)
