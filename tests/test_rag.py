from netdiag_agent.rag import HashingEmbeddingFunction, tokenize


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
