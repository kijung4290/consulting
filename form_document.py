"""워드·한글 문서처럼 보이는 표 양식 HTML 생성 및 채우기 도구."""

import html as html_lib
import re
from typing import Dict, List, Tuple


PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


def extract_guide_fields(guide: str) -> Tuple[str, List[str]]:
    """기본 AI 지침의 마크다운 출력 구조에서 제목과 항목명을 추출합니다."""
    title_match = re.search(r"^\s*#{1,6}\s*\[?([^\]\n]+)\]?\s*$", guide, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else "상담 기록지"
    fields = []
    for line in guide.splitlines():
        match = re.match(r"^\s*(?:\d+[.)]|[-*])\s*\*\*(.+?)\*\*\s*:", line)
        if match:
            label = match.group(1).strip()
            if label not in fields:
                fields.append(label)
    return title, fields


def build_form_html(template_name: str, guide: str) -> str:
    """기본 템플릿을 인쇄 가능한 2열 표 문서로 구성합니다."""
    extracted_title, fields = extract_guide_fields(guide)
    title = extracted_title or template_name
    if not fields:
        fields = ["주요 내용", "담당자 소견", "처리 결과 및 향후 계획"]
    rows = "".join(
        "<tr>"
        f"<td style='background:#eaf1ee;font-weight:700;width:24%;'>{html_lib.escape(field)}</td>"
        f"<td style='min-height:62px;'>{{{{{html_lib.escape(field)}}}}}</td>"
        "</tr>"
        for field in fields
    )
    return f"""
    <div style="font-family:'Malgun Gothic'; color:#1f2937;">
      <h2 style="text-align:center; margin:8px 0 16px 0;">{html_lib.escape(title)}</h2>
      <table border="1" cellspacing="0" cellpadding="7" width="100%" style="border-collapse:collapse; border-color:#849792;">
        <tr>
          <td style="background:#eaf1ee;font-weight:700;width:16%;">대상자</td><td style="width:34%;">{{{{대상자명}}}}</td>
          <td style="background:#eaf1ee;font-weight:700;width:16%;">상담일</td><td style="width:34%;">{{{{상담일자}}}}</td>
        </tr>
        <tr>
          <td style="background:#eaf1ee;font-weight:700;">작성자</td><td>{{{{작성자}}}}</td>
          <td style="background:#eaf1ee;font-weight:700;">상담방법</td><td>{{{{상담방법}}}}</td>
        </tr>
      </table>
      <p style="margin:8px 0;"></p>
      <table border="1" cellspacing="0" cellpadding="8" width="100%" style="border-collapse:collapse; border-color:#849792;">
        <tr><th style="background:#dceae5;width:24%;">구분</th><th style="background:#dceae5;">기록 내용</th></tr>
        {rows}
      </table>
    </div>
    """.strip()


def build_blank_form_html() -> str:
    return build_form_html(
        "새 서류 양식",
        """### [새 서류 양식]
1. **주요 내용**:
2. **담당자 소견**:
3. **처리 결과 및 향후 계획**:
""",
    )


def parse_generated_sections(text: str) -> Dict[str, str]:
    """AI 마크다운 결과를 양식 셀에 넣을 항목별 내용으로 나눕니다."""
    sections: Dict[str, List[str]] = {}
    current_label = None
    heading_pattern = re.compile(
        r"^\s*(?:(?:\d+[.)]|[-*])\s*)?(?:\*\*)?([^\n:*]{1,90})(?:\*\*)?\s*:\s*(.*)$"
    )
    bracket_pattern = re.compile(r"^\s*\[([^\]]+)\]\s*(.*)$")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if current_label and sections[current_label] and sections[current_label][-1] != "":
                sections[current_label].append("")
            continue
        if line.startswith("#"):
            continue
        match = heading_pattern.match(line) or bracket_pattern.match(line)
        if match:
            label = re.sub(r"\*", "", match.group(1)).strip()
            # 짧은 구조 제목만 필드로 취급해 일반 문장 속 콜론과 구분합니다.
            if len(label) <= 90:
                current_label = label
                sections.setdefault(label, [])
                value = match.group(2).strip()
                if value:
                    sections[label].append(value)
                continue
        if current_label:
            sections[current_label].append(line.lstrip("-* "))
    return {label: "\n".join(lines).strip() for label, lines in sections.items()}


def _normalize_label(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", value.lower())


def _to_html_text(value: str) -> str:
    return html_lib.escape(value or "").replace("\n", "<br>")


def extract_body_html(document_html: str) -> str:
    """QTextDocument 전체 HTML에서 다른 문서에 넣을 body 내용만 추출합니다."""
    match = re.search(r"<body[^>]*>(.*)</body>", document_html or "", re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else (document_html or "")


def render_approval_line_html(steps: List[Dict[str, str]]) -> str:
    """우측 상단에 배치할 인쇄용 결재라인 표를 생성합니다."""
    cleaned = [
        {
            "title": str(step.get("title", "")).strip(),
            "name": str(step.get("name", "")).strip(),
        }
        for step in (steps or [])
        if isinstance(step, dict) and str(step.get("title", "")).strip()
    ][:8]
    if not cleaned:
        return ""
    width = min(68, max(38, 14 + len(cleaned) * 12))
    title_cells = "".join(
        f"<th style='background:#eaf1ee;text-align:center;min-width:58px;'>{html_lib.escape(step['title'])}</th>"
        for step in cleaned
    )
    signature_cells = "".join(
        "<td style='height:46px;text-align:center;vertical-align:middle;'>"
        f"{html_lib.escape(step['name'])}"
        "</td>"
        for step in cleaned
    )
    return f"""
    <div style="text-align:right; margin:0 0 8px 0;">
      <table class="approval-line" align="right" border="1" cellspacing="0" cellpadding="5" width="{width}%"
             style="border-collapse:collapse;border-color:#65756f;width:{width}%;margin-left:auto;">
        <tr><th rowspan="2" style="background:#dceae5;text-align:center;width:38px;">결재</th>{title_cells}</tr>
        <tr>{signature_cells}</tr>
      </table>
    </div>
    <p style="clear:both;margin:0 0 6px 0;"><br></p>
    """.strip()


def inject_approval_line(form_html: str, steps: List[Dict[str, str]]) -> str:
    """저장된 본문 양식의 우측 상단에 현재 사용자의 결재라인을 넣습니다."""
    approval_html = render_approval_line_html(steps)
    if not approval_html:
        return form_html
    body_match = re.search(r"<body[^>]*>", form_html or "", re.IGNORECASE)
    if body_match:
        insert_at = body_match.end()
        return form_html[:insert_at] + approval_html + form_html[insert_at:]
    heading_match = re.search(r"<h[1-6][^>]*>", form_html or "", re.IGNORECASE)
    if heading_match:
        insert_at = heading_match.start()
        return form_html[:insert_at] + approval_html + form_html[insert_at:]
    return approval_html + (form_html or "")


def fill_form_html(
    form_html: str,
    metadata: Dict[str, str] = None,
    generated_text: str = "",
) -> str:
    """표 양식의 {{필드명}} 자리에 기본정보와 AI 결과를 채웁니다."""
    metadata = metadata or {}
    sections = parse_generated_sections(generated_text)
    normalized_sections = {_normalize_label(key): value for key, value in sections.items()}
    placeholders = PLACEHOLDER_PATTERN.findall(form_html)
    matched_content_fields = 0
    output = form_html

    # "성별"을 "보호자 성별"에 재사용하는 등, 빈 항목에 다른 사람의
    # 정보가 들어가지 않도록 양식에 더 구체적인 필드가 있으면 제외합니다.
    normalized_placeholders = {_normalize_label(field) for field in placeholders}
    for placeholder in placeholders:
        clean_placeholder = placeholder.strip()
        replacement = metadata.get(clean_placeholder)
        if replacement is None:
            normalized_placeholder = _normalize_label(clean_placeholder)
            replacement = normalized_sections.get(normalized_placeholder)
            if replacement is None:
                for normalized_label, section_value in normalized_sections.items():
                    if normalized_label in normalized_placeholders:
                        continue
                    if normalized_placeholder in normalized_label or normalized_label in normalized_placeholder:
                        replacement = section_value
                        break
            if replacement:
                matched_content_fields += 1
        token_pattern = re.compile(r"\{\{\s*" + re.escape(clean_placeholder) + r"\s*\}\}")
        output = token_pattern.sub(_to_html_text(replacement or ""), output)

    # 사용자 제작 양식과 AI 항목명이 전혀 맞지 않을 때도 결과가 사라지지 않게 본문을 덧붙입니다.
    if generated_text.strip() and matched_content_fields == 0:
        output += (
            "<p style='margin-top:10px;font-weight:700;'>AI 작성 내용</p>"
            f"<div style='border:1px solid #849792;padding:10px;'>{_to_html_text(generated_text)}</div>"
        )
    return output
