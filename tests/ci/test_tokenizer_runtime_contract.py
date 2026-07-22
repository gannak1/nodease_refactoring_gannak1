from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GATEWAY_DOCKERFILE = ROOT / "docker" / "gateway" / "Dockerfile"
WORKFLOW_DOCKERFILE = ROOT / "docker" / "workflow_engine" / "Dockerfile"
INGESTION_SERVICE = ROOT / "apps" / "gateway" / "services" / "ingestion" / "service.py"


def test_gateway_image_preloads_runtime_tokenizers_and_nltk_resources() -> None:
    dockerfile = GATEWAY_DOCKERFILE.read_text(encoding="utf-8")

    assert "TIKTOKEN_CACHE_DIR=/opt/tokenizer-cache" in dockerfile
    assert "NLTK_DATA=/opt/nltk-data" in dockerfile
    assert "get_encoding('cl100k_base')" in dockerfile
    assert "get_encoding('o200k_base')" in dockerfile
    assert "nltk.download(name" in dockerfile
    for resource in ("'punkt'", "'punkt_tab'", "'stopwords'"):
        assert resource in dockerfile
    assert "COPY --from=builder /tokenizer-cache /opt/tokenizer-cache" in dockerfile
    assert "COPY --from=builder /nltk-data /opt/nltk-data" in dockerfile


def test_workflow_image_preloads_runtime_tokenizers() -> None:
    dockerfile = WORKFLOW_DOCKERFILE.read_text(encoding="utf-8")

    assert "TIKTOKEN_CACHE_DIR=/opt/tokenizer-cache" in dockerfile
    assert "NLTK_DATA=/opt/nltk-data" in dockerfile
    assert "get_encoding('cl100k_base')" in dockerfile
    assert "get_encoding('o200k_base')" in dockerfile
    assert "nltk.download(name" in dockerfile
    for resource in ("'punkt'", "'punkt_tab'", "'stopwords'"):
        assert resource in dockerfile
    assert "COPY --from=builder /tokenizer-cache /opt/tokenizer-cache" in dockerfile
    assert "COPY --from=builder /nltk-data /opt/nltk-data" in dockerfile


def test_ingestion_never_downloads_nltk_resources_at_runtime() -> None:
    source = INGESTION_SERVICE.read_text(encoding="utf-8")

    assert "nltk.download" not in source
    for resource in (
        '"tokenizers/punkt"',
        '"tokenizers/punkt_tab"',
        '"corpora/stopwords"',
    ):
        assert resource in source


def test_workflow_image_prefetches_opt_in_rag_reranker() -> None:
    dockerfile = WORKFLOW_DOCKERFILE.read_text(encoding="utf-8")

    assert (
        "ARG RAG_CROSS_ENCODER_MODEL_ID="
        "cross-encoder/ms-marco-MiniLM-L-12-v2"
    ) in dockerfile
    assert 'if [ "$INSTALL_RAG_RERANKER" = "true" ]' in dockerfile
    assert "from sentence_transformers import CrossEncoder" in dockerfile
    assert "CrossEncoder('${RAG_CROSS_ENCODER_MODEL_ID}', device='cpu')" in dockerfile
    assert "HF_HOME=/model-routing-hf-cache" in dockerfile
    assert "COPY --from=builder /model-routing-hf-cache /opt/huggingface" in dockerfile
