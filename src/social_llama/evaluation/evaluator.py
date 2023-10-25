"""Evaluation of the model."""

import os
from typing import Dict
from typing import List

import pandas as pd
from datasets import Dataset
from dotenv import load_dotenv
from huggingface_hub import InferenceClient
from tqdm import tqdm
from transformers import AutoConfig
from transformers import AutoTokenizer
from transformers import pipeline

from social_llama.config import DATA_DIR_EVALUATION_SOCIAL_DIMENSIONS
from social_llama.config import DATA_DIR_EVALUATION_SOCKET
from social_llama.config import LlamaConfigs
from social_llama.data_processing.social_dimensions import SocialDimensions
from social_llama.evaluation.helper_functions import label_check
from social_llama.utils import get_device
from social_llama.utils import save_json


load_dotenv()


class Evaluator:
    """Evaluator for our tasks dataset."""

    def __init__(self, model_id: str) -> None:
        """Initialize the evaluator."""
        self.socket_tasks: List[str] = ["CLS", "REG", "PAIR", "SPAN"]
        self.model_id = model_id
        self.social_dimensions = SocialDimensions(
            task="zero-shot", model="meta-llama/Llama-2-7b-chat-hf"
        )
        self.social_dimensions.get_data()
        self.llama_config = LlamaConfigs
        self.socket_prompts: pd.DataFrame = pd.read_csv(
            DATA_DIR_EVALUATION_SOCKET / "socket_prompts.csv"
        )
        self.generation_kwargs = {"max_new_tokens": 20, "temperature": 0.9}
        if model_id in ["meta-llama/Llama-2-7b-chat-hf"]:
            self.inference_client = InferenceClient(
                model=model_id, token=os.environ["HUGGINGFACEHUB_API_TOKEN"]
            )
        else:
            self.tokenizer = AutoTokenizer.from_pretrained(model_id)
            self.config = AutoConfig.from_pretrained(model_id)
            self.llama_config = LlamaConfigs
            self.device = get_device()
            self.llm = pipeline(
                "text-generation",
                model=model_id,
                tokenizer=self.tokenizer,
                # device=self.device,
                device_map="auto",
            )

    def predict(self, task: str = "social-dimensions") -> None:
        """Predict the labels for the test data."""
        if task == "social-dimensions":
            task_data = self._prepare_social_dim_test_data()
            predictions = []

            for sample in tqdm(task_data):
                # prediction = self.llm(sample["prompt"])
                prediction = self.inference_client.text_generation(
                    sample["prompt"], **self.generation_kwargs
                )
                prediction_processed = label_check(
                    prediction=prediction, labels=self.social_dimensions.config.labels
                )
                predictions.append(
                    {
                        "idx": sample["idx"],
                        "prompt": sample["prompt"],
                        "prediction": prediction,
                        "prediction_processed": prediction_processed,
                        "label": sample["label"],
                    }
                )

            save_json(
                DATA_DIR_EVALUATION_SOCIAL_DIMENSIONS
                / f"{self.model_id}_predictions.json",
                predictions,
            )

    def _prepare_social_dim_test_data(self) -> List[Dict[str, str]]:
        """Prepare the test data for the social dimension task."""
        test_data: Dataset = self.social_dimensions.test_data

        test_data_formatted = {}

        # Loop through each JSON object and group by 'idx'
        for obj in test_data:
            idx = obj["idx"]
            response_good = obj["response_good"]

            if idx not in test_data_formatted:
                test_data_formatted[idx] = {
                    "label": [],
                    "idx": idx,
                    "prompt": self.social_dimensions._prompt_function(obj, is_q_a=True),
                }

            test_data_formatted[idx]["label"].append(response_good)

        # Return a list of all the values in the dictionary
        return list(test_data_formatted.values())


if __name__ == "__main__":
    evaluator = Evaluator("meta-llama/Llama-2-7b-chat-hf")

    evaluator.predict()

    a = 1
