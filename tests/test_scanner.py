import unittest

from vrsoft_extractor.scanner import (
    LinkCandidate,
    SectionSpec,
    _extract_media_urls_from_html,
    _habilize_page_urls,
    _sanitize_url_for_debug,
    _should_follow,
)


BASE_URL = "https://vrsoft.endoo.com.br"


class ScannerTest(unittest.TestCase):
    def test_should_follow_accepts_arquivos_subtree(self):
        spec = SectionSpec(area="biblioteca", label="Biblioteca", root_path="/arquivos")
        self.assertTrue(
            _should_follow(
                LinkCandidate(url=f"{BASE_URL}/arquivos/pasta/video-aula", text="Video aula"),
                spec,
                BASE_URL,
            )
        )

    def test_should_follow_accepts_cursos_subtree(self):
        spec = SectionSpec(area="curso", label="Cursos", root_path="/cursos")
        self.assertTrue(
            _should_follow(
                LinkCandidate(url=f"{BASE_URL}/cursos/curso/conteudo/concluido/8347/10908508", text="Aula"),
                spec,
                BASE_URL,
            )
        )

    def test_should_follow_rejects_global_and_admin_paths(self):
        spec = SectionSpec(area="curso", label="Cursos", root_path="/cursos")
        rejected = [
            f"{BASE_URL}/admin/usuarios",
            f"{BASE_URL}/blog",
            f"{BASE_URL}/wiki",
            f"{BASE_URL}/lojinha",
            f"{BASE_URL}/dashboard",
            f"{BASE_URL}/minha-performance",
        ]
        for url in rejected:
            with self.subTest(url=url):
                self.assertFalse(_should_follow(LinkCandidate(url=url, text="Link"), spec, BASE_URL))

    def test_should_follow_rejects_subscription_actions(self):
        spec = SectionSpec(area="curso", label="Cursos", root_path="/cursos")
        self.assertFalse(
            _should_follow(
                LinkCandidate(url=f"{BASE_URL}/cursos/inscrever/123", text="Inscrever-se"),
                spec,
                BASE_URL,
            )
        )

    def test_extract_media_urls_from_html(self):
        html = """
        <video src="https://cdn.example.com/aula.mp4?token=abc"></video>
        <source src="/media/master.m3u8">
        <iframe src="https://player.vimeo.com/video/123"></iframe>
        """
        urls = _extract_media_urls_from_html(
            html,
            f"{BASE_URL}/arquivos/aula",
            extra_urls=["https://player.vimeo.com/video/123"],
        )

        self.assertIn("https://cdn.example.com/aula.mp4?token=abc", urls)
        self.assertIn(f"{BASE_URL}/media/master.m3u8", urls)
        self.assertIn("https://player.vimeo.com/video/123", urls)

    def test_sanitize_url_for_debug_redacts_sensitive_query_values(self):
        url = "https://cdn.example.com/aula.m3u8?token=abc&expires=123&signature=secret"
        self.assertEqual(
            _sanitize_url_for_debug(url),
            "https://cdn.example.com/aula.m3u8?token=%2A%2A%2A&expires=123&signature=%2A%2A%2A",
        )

    def test_habilize_page_urls(self):
        urls = _habilize_page_urls(
            '<a href="#1.html">1</a><a href="#2.html">2</a>',
            "https://example.com/uploads/course/index.html",
        )
        self.assertEqual(
            urls,
            [
                "https://example.com/uploads/course/pages/1.html",
                "https://example.com/uploads/course/pages/2.html",
            ],
        )


if __name__ == "__main__":
    unittest.main()
