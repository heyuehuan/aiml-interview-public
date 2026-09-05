"""the inline-link branch must not emit javascript:/data: hrefs."""
import mdrender


def test_https_and_mailto_links_render():
    out = mdrender.render("[docs](https://example.com/a?b=1) [mail](mailto:x@y.z)")
    assert '<a href="https://example.com/a?b=1"' in out
    assert '<a href="mailto:x@y.z"' in out


def test_relative_and_fragment_links_render():
    out = mdrender.render("[rel](/problems#q1) [frag](#q2)")
    assert '<a href="/problems#q1"' in out
    assert '<a href="#q2"' in out


def test_javascript_and_data_links_are_neutralized():
    out = mdrender.render("[x](javascript:alert(1)) [y](data:text/html;base64,xx) [z](VBSCRIPT:evil)")
    assert "<a " not in out
    assert "javascript:alert(1)" in out  # kept as visible literal text, not a link


def test_colon_in_query_still_allowed():
    out = mdrender.render("[q](/search?when=12:30)")
    assert '<a href="/search?when=12:30"' in out
