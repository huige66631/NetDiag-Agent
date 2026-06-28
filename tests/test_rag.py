from netdiag_agent.rag import HashingEmbeddingFunction, build_retrieval_query, rewrite_retrieval_terms, tokenize


def test_hashing_embedding_is_normalized_and_stable():
    embedder = HashingEmbeddingFunction(dimensions=32)

    first = embedder.embed_query(["DNS 解析慢，网页打不开"])[0]
    second = embedder.embed_query(["DNS 解析慢，网页打不开"])[0]

    assert first == second
    assert len(first) == 32
    assert any(value != 0 for value in first)


def test_tokenize_supports_chinese_and_latin_terms():
    tokens = tokenize("Wi-Fi 打游戏跳 Ping DNS 慢")

    assert "wi-fi" in tokens
    assert "dns" in tokens
    assert "游戏" in tokens


def test_rewrite_retrieval_terms_adds_domain_labels_for_gaming_symptoms():
    terms = rewrite_retrieval_terms("晚上打游戏一卡一卡的，偶尔跳 ping")

    assert "游戏卡顿" in terms
    assert "延迟波动" in terms
    assert "抖动" in terms


def test_rewrite_retrieval_terms_returns_empty_for_blank_text():
    assert rewrite_retrieval_terms("") == []


def test_build_retrieval_query_includes_rewrite_terms():
    query = build_retrieval_query("连上 WiFi 但是总跳认证页，网页打不开")

    assert "检索增强标签：" in query
    assert "门户认证" in query
    assert "WiFi接入异常" in query
