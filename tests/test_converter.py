import json
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest import mock

from chm_agent.converter import ConversionError, _extract, convert


class ConverterTest(unittest.TestCase):
    def test_converts_extracted_chm_and_respects_toc(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, output = root / "source", root / "output"
            source.mkdir()
            (source / "toc.hhc").write_text(
                '<ul><li><object><param name="Name" value="第二章">'
                '<param name="Local" value="second.htm"></object></li>'
                '<li><object><param name="Name" value="第一章">'
                '<param name="Local" value="first.htm"></object></li></ul>',
                encoding="utf-8",
            )
            (source / "first.htm").write_text(
                "<html><head><title>First</title><script>bad()</script></head>"
                '<body><h1>开始</h1><p>这是第一章的有效正文内容。</p>'
                '<a href="second.htm#config">下一章</a>'
                '<a href="downloads/plan.zip">规划包</a>'
                '<a href="downloads/space%20plan.xlsx">规划表</a></body></html>',
                encoding="utf-8",
            )
            (source / "second.htm").write_text(
                "<html><head><title>Second</title></head>"
                "<body><h2>配置</h2><p>这是第二章的有效配置说明。</p>"
                '<img alt="界面" src="images/ui.png"></body></html>',
                encoding="utf-8",
            )
            (source / "images").mkdir()
            (source / "images" / "ui.png").write_bytes(b"image")
            (source / "downloads").mkdir()
            (source / "downloads" / "plan.zip").write_bytes(b"archive")
            (source / "downloads" / "space plan.xlsx").write_bytes(b"sheet")

            result = convert(source, output)

            self.assertEqual(result.page_count, 2)
            catalog = (output / "CATALOG.md").read_text(encoding="utf-8")
            self.assertLess(catalog.index("第二章"), catalog.index("第一章"))
            docs = list((output / "docs").glob("*.md"))
            self.assertEqual(len(docs), 2)
            all_docs = "".join(p.read_text() for p in docs)
            self.assertNotIn("bad()", all_docs)
            self.assertNotIn("Second", all_docs)
            self.assertIn("../assets/images/ui.png", all_docs)
            second_name = next(path.name for path in docs if "第二章" in path.name)
            self.assertIn(f"[下一章]({second_name}#config)", all_docs)
            self.assertIn("[规划包](../assets/downloads/plan.zip)", all_docs)
            self.assertIn("[规划表](../assets/downloads/space%20plan.xlsx)", all_docs)
            self.assertTrue((output / "assets" / "downloads" / "plan.zip").is_file())
            self.assertTrue((output / "assets" / "images" / "ui.png").is_file())
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["format"], "chm-agent-docs/v1")

    def test_does_not_overwrite_without_force(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, output = root / "source", root / "output"
            source.mkdir()
            output.mkdir()
            with self.assertRaises(ConversionError):
                convert(source, output)

    def test_prefers_7z_on_windows(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, output = root / "manual.chm", root / "extracted"
            source.write_bytes(b"chm")
            output.mkdir()

            def run(command, **kwargs):
                (output / "index.html").write_text("<p>安装文档正文</p>", encoding="utf-8")
                return CompletedProcess(command, 0, "", "")

            with (
                mock.patch("chm_agent.converter._is_windows", return_value=True),
                mock.patch("chm_agent.converter._find_7z", return_value=r"C:\Program Files\7-Zip\7z.exe"),
                mock.patch("chm_agent.converter._find_hh") as find_hh,
                mock.patch("chm_agent.converter.subprocess.run", side_effect=run) as subprocess_run,
            ):
                result = _extract(source, output)

            self.assertEqual(result, output)
            self.assertEqual(subprocess_run.call_args.args[0][0], r"C:\Program Files\7-Zip\7z.exe")
            self.assertIn("x", subprocess_run.call_args.args[0])
            find_hh.assert_not_called()

    def test_falls_back_to_hh_on_windows(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, output = root / "manual.chm", root / "extracted"
            source.write_bytes(b"chm")
            output.mkdir()

            def run(command, **kwargs):
                (output / "index.htm").write_text("<p>安装文档正文</p>", encoding="utf-8")
                return CompletedProcess(command, 0, "", "")

            with (
                mock.patch("chm_agent.converter._is_windows", return_value=True),
                mock.patch("chm_agent.converter._find_7z", return_value=None),
                mock.patch("chm_agent.converter._find_hh", return_value=r"C:\Windows\hh.exe"),
                mock.patch("chm_agent.converter.subprocess.run", side_effect=run) as subprocess_run,
            ):
                _extract(source, output)

            self.assertEqual(
                subprocess_run.call_args.args[0],
                [r"C:\Windows\hh.exe", "-decompile", str(output), str(source)],
            )

    def test_rejects_chm_extraction_outside_windows(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, output = root / "manual.chm", root / "extracted"
            source.write_bytes(b"chm")
            output.mkdir()
            with mock.patch("chm_agent.converter._is_windows", return_value=False):
                with self.assertRaisesRegex(ConversionError, "仅支持 Windows"):
                    _extract(source, output)


if __name__ == "__main__":
    unittest.main()
