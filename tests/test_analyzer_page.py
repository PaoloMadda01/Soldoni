def test_page_analyzer_importable():
    from soldoni.app.dashboard import page_analyzer
    assert callable(page_analyzer)
