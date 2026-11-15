#!/usr/bin/env python3
"""Validate the offline HTML prototype template with only the Python standard library."""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path


class TagCollector(HTMLParser):
    """Collect tags and basic nesting information without third-party packages."""

    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.ids: list[str] = []
        self.open_tags: list[str] = []
        self.mismatched_end_tags: list[str] = []

    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        self.tags.append(normalized)
        for name, value in attrs:
            if name.lower() == "id" and value:
                self.ids.append(value)
        if normalized not in self.VOID_TAGS:
            self.open_tags.append(normalized)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag.lower())

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized not in self.open_tags:
            self.mismatched_end_tags.append(normalized)
            return
        if self.open_tags[-1] != normalized:
            self.mismatched_end_tags.append(normalized)
            while self.open_tags and self.open_tags[-1] != normalized:
                self.open_tags.pop()
        if self.open_tags:
            self.open_tags.pop()


def has_tag(tags: list[str], tag: str) -> bool:
    return tag in tags


def detect_prototype_type(content: str) -> str:
    """Infer the prototype family from stable structural markers."""
    app_markers = ("class=\"phone\"", "class=\"screen\"", "m-header", "m-footer", "data-preview")
    web_markers = ("app-shell", "prototype-pane", "requirements-pane", "table-wrap")
    app_hits = sum(marker in content for marker in app_markers)
    web_hits = sum(marker in content for marker in web_markers)
    if app_hits >= 3:
        return "APP/H5"
    if web_hits >= 2:
        return "Web"
    return "未知"


def print_group(title: str, items: list[str]) -> None:
    print(f"\n{title}")
    if not items:
        print("  （无）")
        return
    for item in items:
        print(f"  - {item}")


def validate_html(path: Path) -> tuple[list[str], list[str], list[str]]:
    passed: list[str] = []
    warnings: list[str] = []
    failed: list[str] = []

    if path.exists():
        passed.append("文件存在")
    else:
        failed.append("文件不存在")
        return passed, warnings, failed

    if path.is_file():
        passed.append("路径指向普通文件")
    else:
        failed.append("路径不是普通文件")
        return passed, warnings, failed

    if path.suffix.lower() in {".html", ".htm"}:
        passed.append("文件扩展名为 HTML")
    else:
        failed.append("文件扩展名不是 .html 或 .htm")

    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        failed.append("文件不是 UTF-8 编码，无法稳定读取")
        return passed, warnings, failed
    except OSError as exc:
        failed.append(f"文件读取失败：{exc}")
        return passed, warnings, failed

    if len(content.strip()) >= 200:
        passed.append("文件不是明显的空文件")
    else:
        failed.append("文件内容过少，疑似空文件或占位文件")

    parser = TagCollector()
    try:
        parser.feed(content)
        parser.close()
    except Exception as exc:  # HTMLParser normally tolerates malformed HTML.
        failed.append(f"HTML 标签解析失败：{exc}")

    required_tags = ("html", "head", "body")
    missing_tags = [tag for tag in required_tags if not has_tag(parser.tags, tag)]
    if not missing_tags:
        passed.append("包含 html、head、body 标签")
    else:
        failed.append(f"缺少必要标签：{', '.join(missing_tags)}")

    for tag in ("style", "script"):
        if has_tag(parser.tags, tag):
            passed.append(f"包含 {tag} 标签")
        else:
            failed.append(f"缺少 {tag} 标签")

    external_cdn_patterns = [
        r"<script\b[^>]+\bsrc\s*=\s*[\"'](?:https?:)?//",
        r"<link\b[^>]+\b(?:href|src)\s*=\s*[\"'](?:https?:)?//",
        # Base64 data URLs can contain both "//" and "cdn" by chance.
        # Require a URL scheme or a quoted/parenthesized protocol-relative URL.
        r"(?:https?://|[\"'(=]\s*//)[^\s\"']*cdn[^\s\"']*",
    ]
    external_cdn_found = any(re.search(pattern, content, flags=re.IGNORECASE) for pattern in external_cdn_patterns)
    if external_cdn_found:
        failed.append("发现外部 CDN 或远程资源引用")
    else:
        passed.append("未发现外部 CDN 或远程资源引用")

    layout_markers = (
        "app-shell",
        "prototype-pane",
        "requirements-pane",
        "grid-template-columns",
        "左右布局",
    )
    layout_hits = [marker for marker in layout_markers if marker in content]
    if len(layout_hits) >= 2:
        passed.append("包含左右布局相关结构")
    else:
        failed.append("未识别到足够的左右布局相关结构")

    requirement_markers = ("requirements-pane", "requirement-content", "需求说明")
    requirement_hits = [marker for marker in requirement_markers if marker in content]
    if len(requirement_hits) >= 2:
        passed.append("包含需求说明区域")
    else:
        failed.append("未识别到需求说明区域")

    interaction_patterns = (
        r"addEventListener\s*\(",
        r"onclick\s*=",
        r"function\s+[A-Za-z_$][\w$]*\s*\(",
    )
    interaction_hits = [pattern for pattern in interaction_patterns if re.search(pattern, content)]
    if len(interaction_hits) >= 1:
        passed.append("包含基础交互脚本")
    else:
        failed.append("未识别到基础交互脚本")

    if not re.search(r"<meta\b[^>]+charset=", content, flags=re.IGNORECASE):
        warnings.append("未识别到 charset 声明")
    if not re.search(r"<meta\b[^>]+name=[\"']viewport[\"']", content, flags=re.IGNORECASE):
        warnings.append("未识别到 viewport 声明，桌面适配仍建议人工检查")
    if not re.search(r"<!doctype\s+html", content, flags=re.IGNORECASE):
        warnings.append("未识别到 HTML5 doctype")

    prototype_type = detect_prototype_type(content)
    if prototype_type == "APP/H5":
        app_checks = [
            ("包含手机外壳结构", re.search(r'class=["\'][^"\']*\bphone\b', content, flags=re.IGNORECASE)),
            ("包含手机屏幕结构", re.search(r'class=["\'][^"\']*\bscreen\b', content, flags=re.IGNORECASE)),
            ("包含移动端顶部导航", re.search(r"m-header", content, flags=re.IGNORECASE)),
            ("包含独立滚动内容区", re.search(r"m-list|overflow-y\s*:\s*auto", content, flags=re.IGNORECASE)),
            ("包含底部固定操作区", re.search(r"m-footer|btn-cta", content, flags=re.IGNORECASE)),
            ("包含页面状态预览", re.search(r"data-preview|gotoState|preview", content, flags=re.IGNORECASE)),
            ("包含文案编辑机制", re.search(r"data-k|contenteditable", content, flags=re.IGNORECASE)),
            ("包含 HTML 导出能力", re.search(r"exportHTML|outerHTML", content, flags=re.IGNORECASE)),
        ]
        for label, matched in app_checks:
            if matched:
                passed.append(label)
            else:
                failed.append(f"APP/H5 缺少{label[2:]}")

        duplicates = sorted(identifier for identifier, count in Counter(parser.ids).items() if count > 1)
        if duplicates:
            failed.append(f"存在重复 id：{', '.join(duplicates)}")
        else:
            passed.append("未发现重复 id")

        collector_unclosed = getattr(parser, "open_tags", [])
        collector_mismatched = getattr(parser, "mismatched_end_tags", [])
        if collector_unclosed or collector_mismatched:
            detail = []
            if collector_unclosed:
                detail.append(f"未闭合 {', '.join(collector_unclosed[-8:])}")
            if collector_mismatched:
                detail.append(f"不匹配结束标签 {', '.join(collector_mismatched[-8:])}")
            failed.append("基础 HTML 标签结构异常：" + "；".join(detail))
        else:
            passed.append("基础 HTML 标签闭合检查通过")

        if re.search(r"<table\b", content, flags=re.IGNORECASE):
            warnings.append("APP/H5 中发现 table 标签，需确认没有把 Web 宽表格直接放入手机区域")
        else:
            passed.append("未发现 Web 宽表格直接放入手机原型的风险")
    elif prototype_type == "未知":
        warnings.append("无法自动判断原型类型，已仅执行通用 HTML 检查")

    return passed, warnings, failed


def main() -> int:
    parser = argparse.ArgumentParser(description="检查离线需求原型 HTML 的基础结构和交互要素")
    parser.add_argument("html_file", help="待检查的 HTML 文件路径")
    args = parser.parse_args()

    path = Path(args.html_file).expanduser()
    print(f"HTML 校验：{path}")
    try:
        prototype_type = detect_prototype_type(path.read_text(encoding="utf-8")) if path.is_file() else "未知"
    except (OSError, UnicodeDecodeError):
        prototype_type = "未知"
    print(f"原型类型：{prototype_type}")
    passed, warnings, failed = validate_html(path)
    print_group("通过项", passed)
    print_group("警告项", warnings)
    print_group("失败项", failed)

    if failed:
        print("\n最终建议：暂不交付，请先修复失败项。")
        return 1
    print("\n最终建议：可以交付；仍建议在桌面浏览器中完成一次人工交互检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
