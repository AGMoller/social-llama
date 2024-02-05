"""Retrieval-Augmented Generation (RAG) system for classification."""
import logging
import os
from typing import List

import datasets
import torch
from dotenv import load_dotenv
from huggingface_hub import InferenceClient
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.vectorstores.utils import DistanceStrategy
from langchain_core.documents import Document
from torch.utils.data import DataLoader
from tqdm import tqdm
from transformers import AutoTokenizer

from social_llama.config import DATA_DIR_EVALUATION_SOCIAL_DIMENSIONS
from social_llama.config import DATA_DIR_SOCIAL_DIMENSIONS_PROCESSED
from social_llama.config import DATA_DIR_VECTOR_DB
from social_llama.evaluation.helper_functions import label_finder
from social_llama.utils import save_json


# Configure logging
logging.basicConfig(
    filename="logs/rag.log",
    level=logging.INFO,
    format="%(asctime)s:%(levelname)s:%(message)s",
)

load_dotenv()


def convert_data_to_langchain(dataset):
    """Converts a HuggingFace dataset to a list of langchain documents.

    Args:
        dataset (datasets.Dataset): HuggingFace dataset.

    Returns:
        docs (list): List of langchain documents.
    """
    docs = []
    for d in DataLoader(dataset["train"]):
        docs.append(
            Document(
                page_content=d["text"][0],
                metadata={
                    "idx": d["idx"].item(),
                    "label": d["response_good"][0],
                },
            )
        )
    return docs


def make_or_load_vector_db(
    dataset_name: str,
    data: list,
    model_kwargs: dict,
    encode_kwargs: dict,
    model_name_embedding: str = "sentence-transformers/all-MiniLM-l6-v2",
    remake_db: bool = False,
):
    """Creates or loads a vector database.

    Args:
        dataset_name (str): Name of the dataset.
        data (list): List of langchain documents.
        model_name_embedding (str): Name of the pre-trained model to use for the vector database.
        model_kwargs (dict): Model configuration options.
        encode_kwargs (dict): Encoding options.
        remake_db (bool): Whether to remake the vector database.

    Returns:
        db (FAISS): Vector database.
        retriever (FAISSRetriever): Vector database retriever.
    """
    # Initialize an instance of HuggingFaceEmbeddings with the specified parameters
    embeddings = HuggingFaceEmbeddings(
        model_name=model_name_embedding,  # Provide the pre-trained model's path
        model_kwargs=model_kwargs,  # Pass the model configuration options
        encode_kwargs=encode_kwargs,  # Pass the encoding options
    )

    # Check if there exist a vector database with a name
    if (
        os.path.exists(str(DATA_DIR_VECTOR_DB / f"{dataset_name}.faiss"))
        and not remake_db
    ):
        logging.info(f"Vector database {dataset_name}.faiss exists. Loading...")
        db = FAISS.load_local(
            str(DATA_DIR_VECTOR_DB / f"{dataset_name}.faiss"), embeddings
        )

    else:
        logging.info(
            f"Vector database {dataset_name}.faiss does not exist. Creating..."
        )
        # Create an instance of the RecursiveCharacterTextSplitter class with specific parameters.
        # It splits text into chunks of 1000 characters each with a 150-character overlap.
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000, chunk_overlap=150
        )

        # 'data' holds the text you want to split, split the text into documents using the text splitter.
        docs = text_splitter.split_documents(data)

        db = FAISS.from_documents(docs, embeddings)

        # Change distance strategy to cosine similarity
        db.distance_strategy = DistanceStrategy.COSINE

        # Save the vector database to the specified path
        db.save_local(str(DATA_DIR_VECTOR_DB / f"{dataset_name}.faiss"))
        logging.info(f"Vector database {dataset_name}.faiss created and saved.")

    retriever = db.as_retriever(search_kwargs={"k": 4})

    return db, retriever


def decode_documents(response):
    """Decodes the documents returned by the vector database.

    Args:
        response (list): List of tuples containing the document and the score.

    Returns:
        formatted_response (str): Formatted response.
    """
    formatted_response = []
    for idx, (doc, _) in enumerate(response):
        content = doc.page_content
        label = doc.metadata["label"]
        formatted_response.append(
            f'Document {idx+1}: "{content}"\nLabel {idx}: {label}'
        )
    return "\n".join(formatted_response)


class HuggingfaceChatTemplate:
    """Huggingface chat template for RAG."""

    def __init__(self, model_name: str):
        """Initializes the Huggingface chat template.

        Args:
            model_name (str): Name of the pre-trained model.

        Returns:
            None
        """
        self.model_name: str = model_name
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.tokenizer.use_default_system_prompt = False

    def get_template_classification(self, system_prompt: str, task: str) -> str:
        """Gets the template for classification.

        Args:
            system_prompt (str): System prompt.
            task (str): Task.

        Returns:
            template (str): Template.
        """
        chat = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": """{task}\nRetrieved Documents:\n{context}\nInput Text: {text}\nAnswer:""".format(
                    task=task,
                    context="{context}",
                    text="{text}",
                ),
            },
        ]

        return self.tokenizer.apply_chat_template(chat, tokenize=False)


# Load the data
logging.info("Loading training and test datasets.")
dataset_name = "social-dimensions"

if dataset_name == "social-dimensions":
    dataset = datasets.load_dataset(
        "json", data_files=str(DATA_DIR_SOCIAL_DIMENSIONS_PROCESSED / "train.json")
    )
    dataset_test = datasets.load_dataset(
        "json", data_files=str(DATA_DIR_SOCIAL_DIMENSIONS_PROCESSED / "test.json")
    )
    labels = [
        "social_support",
        "conflict",
        "trust",
        "fun",
        "similarity",
        "identity",
        "respect",
        "romance",
        "knowledge",
        "power",
        "other",
    ]
else:
    dataset = datasets.load_dataset(dataset_name, split="train")
    dataset_test = datasets.load_dataset(dataset_name, split="test")
    labels: List[str] = dataset.features["label"].names

# Convert to langchain format
docs = convert_data_to_langchain(dataset)
docs_test = convert_data_to_langchain(dataset_test)

# Make or load vector db
logging.info("Making or loading vector database for 'social-dimensions'.")
# Find the device type # include looking for mps
if torch.cuda.is_available():
    device = "cuda"
elif torch.backends.mps.is_available():
    device = "mps"
else:
    device = "cpu"
logging.info(f"Device type: {device}")

db, retriever = make_or_load_vector_db(
    "social-dimensions",
    docs,
    model_kwargs={"device": device},
    encode_kwargs={"normalize_embeddings": True},
    remake_db=False,
)


# Specify the model name you want to use
model_name = "meta-llama/Llama-2-70b-chat-hf"

llm = InferenceClient(
model=model_name,
token=os.environ["HUGGINGFACEHUB_API_TOKEN"],
)
# Disable caching
llm.headers["x-use-cache"] = "0"

system_prompt = """You are part of a RAG classification system designed to categorize texts.
Your task is to analyze the input text and classify it into one of the provided labels based on your general knowledge and the context provided by any retrieved documents that may be relevant.
Below are the labels you can choose from, along with their descriptions. Use the information from the retrieved documents to aid your decision if they are relevant to the input text.

Labels and Descriptions:
social_support: Giving emotional or practical aid and companionship.
conflict: Contrast or diverging views.
trust: Will of relying on the actions or judgments of another.
fun: Experiencing leisure, laughter, and joy.
similarity: Shared interests, motivations or outlooks.
identity: Shared sense of belonging to the same community or group.
respect: Conferring status, respect, appreciation, gratitude, or admiration upon another.
romance: Intimacy among people with a sentimental or sexual relationship.
knowledge: Exchange of ideas or information; learning, teaching.
power: Having power over the behavior and outcomes of another.
other: If none of the above social dimensions apply.
"""

task = """Using the general knowledge and the information from the retrieved documents provided above, classify the input text by selecting the most appropriate label.
Consider the relevance and content of each document in relation to the input text and the descriptions of the labels.
If a retrieved document is highly relevant to the input text and aligns closely with the description of a label, that label might be the correct classification.
"""

template = HuggingfaceChatTemplate(
    model_name=model_name,
).get_template_classification(
    system_prompt=system_prompt,
    task=task,
)


# Group by idx and collect labels
test_data_formatted = {}

# Loop through each JSON object and group by 'idx'
for obj in DataLoader(dataset_test["train"]):
    idx = obj["idx"].item()
    response_good = obj["response_good"][0]

    if idx not in test_data_formatted:
        test_data_formatted[idx] = {
            "label": [],
            "idx": idx,
            "text": obj["text"][0],
        }

    test_data_formatted[idx]["label"].append(response_good)

# Return a list of all the values in the dictionary
test_data_formatted = list(test_data_formatted.values())

predictions = []

for idx, sample in tqdm(enumerate(test_data_formatted), desc="Predicting"):
    search_docs_text = db.similarity_search_with_score(sample["text"], k=5, fetch_k=10)
    # searchDocs_question = db.similarity_search_with_score(question, k=5, fetch_k=25)

    decoded_text = decode_documents(search_docs_text)
    # decoded_question = decode_documents(searchDocs_question)
    
    has_output = False

    while not has_output:  
        try:
            output = llm.text_generation(
                template.format(
                    context=decoded_text,
                    text=sample["text"],
                ),
                max_new_tokens=100,
                temperature=0.7,
                # repetition_penalty=1.2,
            )
            has_output = True

        except BaseException as e:
            logging.info(f"Error: {e}")
            
            # Delete LLM
            del llm

            logging.info("Reinitializing LLM...")
            llm = InferenceClient(
            model=model_name,
            token=os.environ["HUGGINGFACEHUB_API_TOKEN"],
            )
            # Disable caching
            llm.headers["x-use-cache"] = "0"

    label = label_finder(output, labels)

    predictions.append(
        {
            "idx": idx,
            "text": sample["text"],
            "label": sample["label"],
            "prediction": label,
            "output": output,
            "documents": decoded_text,
        }
    )

save_path = DATA_DIR_EVALUATION_SOCIAL_DIMENSIONS / f"{model_name}_predictions_RAG.json"

# Save predictions to JSON file
save_json(save_path, predictions)
