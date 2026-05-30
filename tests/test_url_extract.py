from researchpapers.url_extract import extract_urls_from_text


def test_basic_url_is_picked_up():
    rows = extract_urls_from_text("see https://github.com/foo/bar for details")
    assert len(rows) == 1
    raw, canonical, scheme, host, _ = rows[0]
    assert raw == "https://github.com/foo/bar"
    assert canonical == "https://github.com/foo/bar"
    assert scheme == "https"
    assert host == "github.com"


def test_trailing_punctuation_is_trimmed():
    rows = extract_urls_from_text("see https://example.com/page. Also: https://foo.org/x),")
    canonicals = {r[1] for r in rows}
    assert canonicals == {"https://example.com/page", "https://foo.org/x"}


def test_soft_hyphen_line_break_is_joined():
    # arxiv PDFs frequently break long URLs with `-\n`
    text = "models are at https://huggingface.co/some-org/some-mod-\nel/tree/main today"
    rows = extract_urls_from_text(text)
    assert any("huggingface.co/some-org/some-model/tree/main" in r[1] for r in rows)


def test_hard_line_break_inside_url_is_joined():
    text = "see https://github.com/foo/\nbar/baz for code"
    rows = extract_urls_from_text(text)
    assert any(r[1] == "https://github.com/foo/bar/baz" for r in rows)


def test_tracking_params_are_dropped():
    rows = extract_urls_from_text("visit https://example.com/p?utm_source=arxiv&id=42")
    assert rows[0][1] == "https://example.com/p?id=42"


def test_dedupe_within_same_text():
    text = "https://x.com/a and again https://x.com/a"
    rows = extract_urls_from_text(text)
    assert len(rows) == 1


def test_non_http_schemes_are_ignored():
    text = "mailto:foo@bar.com and ftp://old.example.com/file"
    rows = extract_urls_from_text(text)
    assert rows == []


def test_host_is_lowercased():
    rows = extract_urls_from_text("see https://GitHub.Com/foo/bar")
    assert rows[0][3] == "github.com"


def test_context_snippet_is_attached():
    text = "padding " * 5 + "in section 3 we link https://example.com/x for the dataset" + " padding" * 5
    rows = extract_urls_from_text(text)
    assert "section 3" in rows[0][4]
    assert "dataset" in rows[0][4]


def test_bled_text_after_host_is_truncated_at_valid_tld():
    """PDF text often runs `http://scikit-learn.org` into the next word like `Keywords:`."""
    text = "downloaded from http://scikit-learn.org.Keywords: Python, supervised learning"
    rows = extract_urls_from_text(text)
    assert any(r[1] == "http://scikit-learn.org" for r in rows)
    assert not any("keywords" in r[1].lower() for r in rows)


def test_host_with_no_valid_tld_is_rejected():
    """Things like `https://blog.and` (when text wrapped from `blog.openai.com`) shouldn't survive."""
    text = "see https://blog.and open in your browser"
    rows = extract_urls_from_text(text)
    assert not any(r[3] == "blog.and" for r in rows)


def test_subdomain_preserved_after_normalization():
    text = "model at https://huggingface.co/bert-base-uncased here"
    rows = extract_urls_from_text(text)
    assert rows[0][3] == "huggingface.co"


def test_long_subdomain_chain_kept_intact():
    text = "see https://blog.cloudflare.com/post"
    rows = extract_urls_from_text(text)
    assert rows[0][3] == "blog.cloudflare.com"
