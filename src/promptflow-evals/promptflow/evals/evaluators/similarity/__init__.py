# ---------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# ---------------------------------------------------------

__path__ = __import__("pkgutil").extend_path(__path__, __name__)  # type: ignore

from promptflow import load_flow
from promptflow.entities import AzureOpenAIConnection
from pathlib import Path


def init(model_config: AzureOpenAIConnection):
    """
    Initialize an evaluation function configured for a specific Azure OpenAI model.

    :param model_config: Configuration for the Azure OpenAI model.
    :type model_config: AzureOpenAIConnection
    :return: A function that evaluates similarity.
    :rtype: function

    **Usage**

    .. code-block:: python

        eval_fn = similarity.init(model_config)
        result = eval_fn(
            question="What is the capital of Japan?",
            answer="The capital of Japan is Tokyo.",
            ground_truth="Tokyo is Japan's capital.")
    """
    def eval_fn(question: str, answer: str, ground_truth: str):
        # Load the flow as function
        current_dir = Path(__file__).resolve().parent
        flow_dir = current_dir / "flow"
        f = load_flow(source=flow_dir)

        # Override the connection
        f.context.connections = {
            "query_llm": { "connection": model_config },
        }

        # Run the evaluation flow
        return f(question=question, answer=answer, ground_truth=ground_truth)
    return eval_fn