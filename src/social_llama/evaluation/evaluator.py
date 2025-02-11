"""Evaluation of the model."""

import os
import sys
import time
from typing import Dict
from typing import List
from typing import Union

import pandas as pd
import torch
from datasets import Dataset
from datasets import disable_caching
from datasets import load_dataset
from dotenv import load_dotenv
from huggingface_hub import InferenceClient
from torch.utils.data import DataLoader
from tqdm import tqdm
from transformers import AutoConfig
from transformers import AutoTokenizer
from transformers import pipeline

# from social_llama.config import DATA_DIR_EVALUATION_SOCIAL_DIMENSIONS
from social_llama.config import DATA_DIR_EVALUATION_SOCKET
from social_llama.config import Configs

# from social_llama.data_processing.social_dimensions import SocialDimensions
from social_llama.evaluation.helper_functions import label_check
from social_llama.evaluation.helper_functions import label_finder
from social_llama.reverse_instructions.instruction_configs import (
    ReverseInstructionsPrompts,
)
from social_llama.utils import get_device
from social_llama.utils import save_json


load_dotenv()

disable_caching()


class Evaluator:
    """Evaluator for our tasks dataset."""

    def __init__(self, model_id: str) -> None:
        """Initialize the evaluator."""
        self.socket_tasks: List[str] = ["CLS", "REG", "PAIR", "SPAN"]
        self.model_id = model_id
        self.is_instruction = True if "instruction" in model_id else False
        if self.is_instruction:
            self.instructions = load_dataset(
                "AndersGiovanni/instructions-SOCKET", split="train"
            )
            self.instructions_prompt_cls: str = (
                ReverseInstructionsPrompts().instruction_cls()
            )
        # self.social_dimensions = SocialDimensions(
        #     task="zero-shot", model="meta-llama/Llama-2-7b-chat-hf"
        # )
        # self.social_dimensions.get_data()
        self.chat_config = Configs()
        self.socket_prompts: pd.DataFrame
        self.generation_kwargs = {
            "max_new_tokens": 50,
            "temperature": 0.9,
            "truncate": 4096,
            # "stop_sequences": self.social_dimensions.config.labels,
        }
        self.generation_kwargs_local = {
            "max_new_tokens": 150,
            "temperature": 0.9,
            "do_sample": True,
        }
        if "llama" in model_id:
            self.tokenizer = AutoTokenizer.from_pretrained(
                # "meta-llama/Llama-2-7b-chat-hf"
                "meta-llama/Meta-Llama-3-8B-Instruct"
            )
        elif "gemma" in model_id:
            self.tokenizer = AutoTokenizer.from_pretrained("google/gemma-7b-it")
        else:
            self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        if model_id in [
            "meta-llama/Llama-2-7b-chat-hf",
            "meta-llama/Llama-2-7b-hf",
            "meta-llama/Llama-2-13b-chat-hf",
            "mistralai/Mistral-7B-Instruct-v0.2",
            "google/gemma-7b-it",
            "meta-llama/Meta-Llama-3-8B-Instruct",
        ]:
            self.inference_client = InferenceClient(
                model=model_id, token=os.environ["HUGGINGFACEHUB_API_TOKEN"]
            )
            self.use_inference_client = True
        else:
            self.config = AutoConfig.from_pretrained(model_id)
            self.chat_config = Configs()
            self.device = get_device()
            self.llm = pipeline(
                "text-generation",
                model=model_id,
                tokenizer=self.tokenizer,
                device_map="auto",
                **self.generation_kwargs_local,
            )
            self.use_inference_client = False

    def predict(
        self, task: str = "social-dimensions", batch_size: int = 8, note: str = ""
    ) -> None:
        """Predict the labels for the test data."""
        self.socket_prompts: pd.DataFrame = pd.read_csv(
            DATA_DIR_EVALUATION_SOCKET / "socket_prompts.csv"
            if note == "zero-shot"
            else DATA_DIR_EVALUATION_SOCKET / "socket_prompts_knowledge.csv"
        )

        if task == "social-dimensions":
            pass
            # task_data = self._prepare_social_dim_test_data()
            # labels = self.social_dimensions.config.labels
            # save_path = (
            #     DATA_DIR_EVALUATION_SOCIAL_DIMENSIONS
            #     / f"{self.model_id}_predictions_{note}.json"
            # )
            # task_data = DataLoader(
            #     task_data,
            #     batch_size=1 if self.use_inference_client else batch_size,
            #     shuffle=False,
            #     num_workers=0,
            #     drop_last=False,
            #     collate_fn=self.collate_fn,
            # )

            # predictions = self._process_samples(task_data, labels)
            # save_json(save_path, predictions)
        elif task == "socket":
            for task in [
                "hahackathon#is_humor",
                "sarc",
                "contextual-abuse#IdentityDirectedAbuse",
                "contextual-abuse#PersonDirectedAbuse",
                "tweet_irony",
                "questionintimacy",
                "tweet_emotion",
                "hateoffensive",
                "implicit-hate#explicit_hate",
                "implicit-hate#implicit_hate",
                "crowdflower",
                "dailydialog",
                "hasbiasedimplication",
                "implicit-hate#stereotypical_hate",
                "intentyn",
                "tweet_offensive",
                "empathy#distress_bin",
                "complaints",
                "hayati_politeness",
                "stanfordpoliteness",
                "hypo-l",
                "rumor#rumor_bool",
                "two-to-lie#receiver_truth",
            ][::-1]:
                task_data, labels = self._prepare_socket_test_data(task=task)
                save_path = (
                    DATA_DIR_EVALUATION_SOCKET
                    / f"{task}/{self.model_id}_predictions_{note}.json"
                )
                task_data = DataLoader(
                    task_data,
                    batch_size=1 if self.use_inference_client else batch_size,
                    shuffle=False,
                    num_workers=0,
                    drop_last=False,
                    collate_fn=self.collate_fn,
                )

                predictions = self._process_samples(task_data, labels)
                save_json(save_path, predictions)
        else:
            raise ValueError("Task not recognized.")

    def _process_samples(self, task_data, labels):
        predictions = []
        for batch in tqdm(task_data):
            batch_predictions: List[str] = self._predict(batch)

            for idx, prompt, label, prediction in zip(
                batch["idx"], batch["prompt"], batch["label"], batch_predictions
            ):
                prediction_processed = label_check(
                    prediction=prediction,
                    labels=labels,
                )
                prediction_finder = label_finder(
                    prediction=prediction,
                    labels=labels,
                )
                predictions.append(
                    {
                        "idx": idx.item(),  # convert tensor to python int
                        "prompt": prompt,
                        "prediction": prediction,
                        "prediction_processed": prediction_processed,
                        "prediction_finder": prediction_finder,
                        "label": label,
                    }
                )
        return predictions

    def _predict(self, sample) -> List[str]:
        prediction: List[str] = []
        if self.use_inference_client:
            has_output = False
            while not has_output:
                try:
                    prediction: List[str] = [
                        self.inference_client.text_generation(
                            sample["prompt"][0], **self.generation_kwargs
                        )
                    ]
                except Exception:
                    time.sleep(2)
                    continue
                has_output = True

        else:
            # Predict
            output: List[List[Dict[str, str]]] = self.llm(sample["prompt"])
            # Select the generated output
            prediction: List[str] = [item[0]["generated_text"] for item in output]
            # Remove the prompt from the output
            prediction: List[str] = [
                pred.replace(prompt, "")
                for pred, prompt in zip(prediction, sample["prompt"])
            ]

        return prediction

    # def _prepare_social_dim_test_data(
    #     self,
    # ) -> List[Dict[str, Union[str, int, List[str]]]]:
    #     """Prepare the test data for the social dimension task."""
    #     test_data: Dataset = self.social_dimensions.test_data

    #     test_data_formatted = {}

    #     # Loop through each JSON object and group by 'idx'
    #     for obj in test_data:
    #         idx = obj["idx"]
    #         response_good = obj["response_good"]

    #         if idx not in test_data_formatted:
    #             test_data_formatted[idx] = {
    #                 "label": [],
    #                 "idx": idx,
    #                 "prompt": self.social_dimensions._prompt_function(obj, is_q_a=True),
    #             }

    #         test_data_formatted[idx]["label"].append(response_good)

    #     # Return a list of all the values in the dictionary
    #     return list(test_data_formatted.values())

    def _prepare_socket_test_data(
        self, task: str
    ) -> List[Dict[str, Union[str, int, List[str]]]]:
        test_data_formatted: List[Dict[str, str]] = []

        dataset: Dataset = load_dataset(
            "Blablablab/SOCKET",
            task,
            split="test",  # trust_remote_code=True
        )
        dataset.cleanup_cache_files()
        # if length is more than 2000, randomly sample 2000
        if len(dataset) > 2000:
            dataset = dataset.shuffle(seed=42).select(range(2000))

        if self.is_instruction:
            prompt = self.instructions_prompt_cls
            # get all instructions from self.instructions where task == task
            task_instructions = (
                self.instructions.filter(
                    lambda example: example["task"] == task
                )  # get all instructions where task == task
                .shuffle(seed=42)  # shuffle the dataset
                .select(range(len(dataset)))  # select the same length as the dataset
            )
        else:
            # Get all the socket prompts with type CLS
            prompt = self.socket_prompts[self.socket_prompts["task"] == task][
                "question"
            ].iloc[0]

            # Get the knowledge of the labels
            # check if knowledge is a column in the dataframe
            knowledge = (
                self.socket_prompts[self.socket_prompts["task"] == task][
                    "knowledge"
                ].iloc[0]
                if "knowledge" in self.socket_prompts.columns
                else pd.NA
            )
            knowledge = "" if pd.isna(knowledge) else knowledge

        labels: List[str] = dataset.features["label"].names
        labels_formatted = [f'"{label}"' for label in labels]
        labels_mapping: Dict[int, str] = {i: label for i, label in enumerate(labels)}

        for idx, sample in enumerate(dataset):
            test_data_formatted.append(
                {
                    "idx": idx,
                    "prompt": (
                        self._prompt_socket(sample, prompt, labels_formatted, knowledge)
                        if not self.is_instruction
                        else self._prompt_socket_instructions(
                            sample,
                            prompt,
                            task_instructions[idx]["instruction"],
                            labels_formatted,
                        )
                    ),
                    "label": labels_mapping[sample["label"]],
                }
            )

        return test_data_formatted, labels

    def _prompt_socket(
        self,
        sample: Dict[str, str],
        prompt: str,
        labels: List[str],
        knowledge: str = "",
    ) -> str:
        chat: List[Dict[str, str]] = self.chat_config.get_chat_template(
            "system" if "llama" in self.model_id else "user"
        )  # A bit too hardcoded, but I assume we on

        chat[0]["content"] = chat[0]["content"].format(
            prompt_prefix=(
                f"You have the following knowledge about task-specific labels: {knowledge}"
                if knowledge != ""
                else ""
            )
        )

        task_prompt = (
            prompt.format(
                text=sample["text"],
            )
            + f" You can choose from the following labels: {', '.join(labels)}\nAnswer:"
        )

        if "llama" in self.model_id:
            chat.append(
                {
                    "role": "user",
                    "content": task_prompt,
                }
            )
        else:
            chat[0] = {
                "role": "user",
                "content": f"{chat[0]['content']} {task_prompt}",  # Gemma is not trained with a system prompt
            }

        return self.tokenizer.apply_chat_template(
            chat, tokenize=False, add_generation_prompt=True
        )

    def _prompt_socket_instructions(
        self, sample: Dict[str, str], prompt: str, instruction: str, labels: List[str]
    ) -> str:
        chat: List[Dict[str, str]] = self.chat_config.get_chat_template(
            "system" if "llama" in self.model_id else "user"
        )  # A bit too hardcoded, but I assume we on

        chat[0]["content"] = chat[0]["content"].format(prompt_prefix="")

        task_prompt: str = prompt.format(
            instruction=instruction,
            text=sample["text"],
            label_list=", ".join(labels),
            label="",
        )

        if "llama" in self.model_id:
            chat.append(
                {
                    "role": "user",
                    "content": task_prompt,
                }
            )
        else:
            chat[0] = {
                "role": "user",
                "content": f"{chat[0]['content']} {task_prompt}",  # Gemma is not trained with a system prompt
            }

        return self.tokenizer.apply_chat_template(
            chat, tokenize=False, add_generation_prompt=True
        )

    def collate_fn(
        self, batch: List[Dict[str, Union[str, int, List[str]]]]
    ) -> Dict[str, Union[torch.Tensor, List[Union[str, int, List[str]]]]]:
        """Collate function for the DataLoader to handle labels list."""
        return {
            "idx": torch.tensor([d["idx"] for d in batch]),
            "prompt": [d["prompt"] for d in batch],
            "label": [d["label"] for d in batch],
        }


if __name__ == "__main__":
    model = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "AndersGiovanni/social-llama-3-8b-instructions"
    )
    # torch.cuda.empty_cache()

    evaluator = Evaluator(model)

    # evaluator.predict(task="social-dimensions")

    evaluator.predict(task="socket", note="zero-shot")

    del evaluator

    a = 1
