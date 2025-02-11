"""Fine-tuning script for DPO training."""

import os
from dataclasses import dataclass
from dataclasses import field
from typing import Optional

import torch
from dotenv import load_dotenv

# from peft import AutoPeftModelForCausalLM
from peft import LoraConfig
from peft import PeftModel
from transformers import AutoModelForCausalLM
from transformers import AutoTokenizer
from transformers import BitsAndBytesConfig
from transformers import HfArgumentParser
from transformers import TrainingArguments
from trl import DPOTrainer

from social_llama.data_processing.combine import Combined
from social_llama.data_processing.instruction_socket import InstructionSocket
from social_llama.data_processing.social_dimensions import SocialDimensions
from social_llama.data_processing.socket import Socket


load_dotenv()


# Define and parse arguments.
@dataclass
class ScriptArguments:
    """The arguments for the DPO training script."""

    # data parameters
    beta: Optional[float] = field(
        default=0.1, metadata={"help": "the beta parameter for DPO loss"}
    )
    # training parameters
    model_name_or_path: Optional[str] = field(
        default="sft/Meta-Llama-3-8B-Instruct_socket_1_epoch/final_checkpoint",
        metadata={"help": "the location of the SFT model name or path"},
    )
    base_model: Optional[str] = field(
        default="meta-llama/Meta-Llama-3-8B-Instruct",
        metadata={"help": "the base model name or path"},
    )
    dataset_name: Optional[str] = field(
        default="socket",
        metadata={"help": "the dataset name"},
    )
    output_dir: Optional[str] = field(
        default="./dpo/Meta-Llama-3-8B-Instruct_socket_1_epoch_1_epoch",
        metadata={"help": "the output directory"},
    )
    learning_rate: Optional[float] = field(
        default=5e-4, metadata={"help": "optimizer learning rate"}
    )
    lr_scheduler_type: Optional[str] = field(
        default="cosine", metadata={"help": "the lr scheduler type"}
    )
    warmup_steps: Optional[int] = field(
        default=100, metadata={"help": "the number of warmup steps"}
    )
    weight_decay: Optional[float] = field(
        default=0.05, metadata={"help": "the weight decay"}
    )
    optimizer_type: Optional[str] = field(
        default="paged_adamw_32bit", metadata={"help": "the optimizer type"}
    )

    per_device_train_batch_size: Optional[int] = field(
        default=2, metadata={"help": "train batch size per device"}
    )
    per_device_eval_batch_size: Optional[int] = field(
        default=1, metadata={"help": "eval batch size per device"}
    )
    gradient_accumulation_steps: Optional[int] = field(
        default=32, metadata={"help": "the number of gradient accumulation steps"}
    )
    gradient_checkpointing: Optional[bool] = field(
        default=True, metadata={"help": "whether to use gradient checkpointing"}
    )

    lora_alpha: Optional[float] = field(
        default=16, metadata={"help": "the lora alpha parameter"}
    )
    lora_dropout: Optional[float] = field(
        default=0.05, metadata={"help": "the lora dropout parameter"}
    )
    lora_r: Optional[int] = field(default=8, metadata={"help": "the lora r parameter"})

    max_prompt_length: Optional[int] = field(
        default=2048, metadata={"help": "the maximum prompt length"}
    )
    max_length: Optional[int] = field(
        default=4096, metadata={"help": "the maximum sequence length"}
    )
    # max_steps: Optional[int] = field(
    #     default=12000, metadata={"help": "max number of training steps"}
    # )
    num_train_epochs: Optional[int] = field(
        default=1, metadata={"help": "max number of training steps"}
    )
    logging_steps: Optional[int] = field(
        default=5, metadata={"help": "the logging frequency"}
    )
    save_steps: Optional[float] = field(
        default=0.1, metadata={"help": "the saving frequency"}
    )
    eval_steps: Optional[float] = field(
        default=0.1, metadata={"help": "the evaluation frequency"}
    )
    log_freq: Optional[int] = field(
        default=1, metadata={"help": "the logging frequency"}
    )

    # instrumentation
    sanity_check: Optional[bool] = field(
        default=False, metadata={"help": "only train on 1000 samples"}
    )
    report_to: Optional[str] = field(
        default="wandb",
        metadata={
            "help": 'The list of integrations to report the results and logs to. Supported platforms are `"azure_ml"`,'
            '`"comet_ml"`, `"mlflow"`, `"neptune"`, `"tensorboard"`,`"clearml"` and `"wandb"`. '
            'Use `"all"` to report to all integrations installed, `"none"` for no integrations.'
        },
    )
    # debug argument for distributed training
    ignore_bias_buffers: Optional[bool] = field(
        default=False,
        metadata={
            "help": "fix for DDP issues with LM bias/mask buffers - invalid scalar type,`inplace operation. See"
            "https://github.com/huggingface/transformers/issues/22482#issuecomment-1595790992"
        },
    )


if __name__ == "__main__":
    parser = HfArgumentParser(ScriptArguments)
    script_args = parser.parse_args_into_dataclasses()[0]

    # Load the base model.
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        # load_in_8bit=True,
        # llm_int8_threshold=6.0,
        # llm_int8_has_fp16_weight=False,
        # bnb_4bit_compute_dtype=torch.bfloat16,
        # bnb_4bit_use_double_quant=True,
        # bnb_4bit_quant_type="nf4",
    )

    # 1. load a pretrained model
    # model = AutoPeftModelForCausalLM.from_pretrained(
    #     script_args.model_name_or_path,
    #     low_cpu_mem_usage=True,
    #     torch_dtype=torch.float32,
    #     load_in_4bit=False,
    #     load_in_8bit=True,
    #     is_trainable=True,
    #     # device_map={"": Accelerator().local_process_index},
    #     # device_map={"":torch.cuda.current_device()}
    # )
    model = AutoModelForCausalLM.from_pretrained(
        script_args.base_model,
        # load_in_4bit=True,
        quantization_config=bnb_config,
        # attn_implementation="flash_attention_2",
        torch_dtype=torch.float32,
        device_map="auto",
    )
    model_ref = AutoModelForCausalLM.from_pretrained(
        script_args.base_model,
        # load_in_4bit=True,
        quantization_config=bnb_config,
        # attn_implementation="flash_attention_2",
        torch_dtype=torch.float32,
        device_map="auto",
    )
    model.config.use_cache = False

    MODEL_NAME = script_args.model_name_or_path.split("/")[-2]
    output_dir = "./dpo/" + MODEL_NAME

    if script_args.ignore_bias_buffers:
        # torch distributed hack
        model._ddp_params_and_buffers_to_ignore = [
            name for name, buffer in model.named_buffers() if buffer.dtype == torch.bool
        ]

    # Load the adapter.
    model = PeftModel.from_pretrained(
        model,
        script_args.model_name_or_path,
        is_trainable=True,
        # adapter_name="train",
    )
    # Load the adapter a second time, with a different name, which will be our reference model.
    # model.load_adapter(script_args.model_name_or_path, adapter_name="reference")

    model_ref = PeftModel.from_pretrained(
        model_ref,
        script_args.model_name_or_path,
        # adapter_name="train",
    )

    # model_ref = AutoPeftModelForCausalLM.from_pretrained(
    #     script_args.model_name_or_path,
    #     low_cpu_mem_usage=True,
    #     torch_dtype=torch.float32,
    #     load_in_4bit=False,
    #     load_in_8bit=True,
    #     # device_map={"": Accelerator().local_process_index},
    #     # device_map={"":torch.cuda.current_device()}
    # )
    if script_args.dataset_name == "social-dimensions":
        dataset = SocialDimensions(task="zero-shot", model=script_args.base_model)
    elif script_args.dataset_name == "socket":
        dataset = Socket(task="zero-shot", model=script_args.base_model)
    elif script_args.dataset_name == "instruction-socket":
        dataset = InstructionSocket(task="zero-shot", model=script_args.base_model)
    elif script_args.dataset_name == "combined":
        dataset = Combined(model=script_args.base_model)

    dataset.get_data()
    train_dataset, eval_dataset = dataset.preprocess_dpo()

    tokenizer = AutoTokenizer.from_pretrained(
        script_args.base_model, trust_remote_code=True
    )
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"  # Fix weird overflow issue with fp16 training
    tokenizer.verbose = False

    # 4. initialize training arguments:
    training_args = TrainingArguments(
        per_device_train_batch_size=script_args.per_device_train_batch_size,
        per_device_eval_batch_size=script_args.per_device_eval_batch_size,
        # max_steps=script_args.max_steps,
        num_train_epochs=script_args.num_train_epochs,
        logging_steps=script_args.logging_steps,
        save_steps=script_args.save_steps,
        gradient_accumulation_steps=script_args.gradient_accumulation_steps,
        gradient_checkpointing=script_args.gradient_checkpointing,
        learning_rate=script_args.learning_rate,
        evaluation_strategy="steps",
        eval_steps=script_args.eval_steps,
        output_dir=script_args.output_dir,
        report_to=script_args.report_to,
        lr_scheduler_type=script_args.lr_scheduler_type,
        warmup_steps=script_args.warmup_steps,
        optim=script_args.optimizer_type,
        # fp16=False,
        bf16=True,
        remove_unused_columns=False,
        run_name=f"dpo_{MODEL_NAME}",
    )

    peft_config = LoraConfig(
        r=script_args.lora_r,
        lora_alpha=script_args.lora_alpha,
        lora_dropout=script_args.lora_dropout,
        target_modules=[
            "q_proj",
            "v_proj",
            "k_proj",
            "out_proj",
            "fc_in",
            "fc_out",
            "wte",
        ],
        # if "llama" in script_args.base_model
        # else [
        #     "q_proj",
        #     "o_proj",
        #     "k_proj",
        #     "v_proj",
        #     "gate_proj",
        #     "up_proj",
        #     "down_proj",
        # ],
        bias="none",
        task_type="CAUSAL_LM",
    )

    # 5. initialize the DPO trainer
    dpo_trainer = DPOTrainer(
        model,
        model_ref,
        args=training_args,
        beta=script_args.beta,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        tokenizer=tokenizer,
        # peft_config=peft_config,
        max_prompt_length=script_args.max_prompt_length,
        max_length=script_args.max_length,
        # model_adapter_name="train",
        # ref_adapter_name="reference",
    )

    # 6. train
    dpo_trainer.train()
    dpo_trainer.save_model(script_args.output_dir)

    # 7. save
    output_dir = os.path.join(script_args.output_dir, "final_checkpoint")
    dpo_trainer.model.save_pretrained(output_dir)
