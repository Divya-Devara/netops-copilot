import os
from langchain_ollama import ChatOllama

def make_llm(model: str | None = None) -> ChatOllama:
    """Single place that builds every Ollama client. Options must match across clients:
    Ollama reloads the model whenever they differ.

    NETOPS_NUM_GPU: layers offloaded to GPU. Default 0 (CPU only): on a 4 GB T400 the 7B model
    split 72/28 CPU/GPU, and prompt processing was ~2x slower than pure CPU (measured 25s vs 14s).
    Unset/empty NETOPS_NUM_GPU to let Ollama decide (e.g. on a bigger GPU).
    """
    kwargs = {}
    ngpu = os.environ.get("NETOPS_NUM_GPU", "0")
    if ngpu != "":
        kwargs["num_gpu"] = int(ngpu)
    return ChatOllama(model=model or os.environ.get("NETOPS_MODEL", "qwen2.5:7b"), temperature=0,
                      keep_alive=os.environ.get("NETOPS_KEEP_ALIVE", "30m"), **kwargs)
