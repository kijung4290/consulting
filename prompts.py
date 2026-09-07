"""사례관리양식 기반 서류 14종과 AI 작성 프롬프트."""

from case_form_templates import CASE_FORM_TEMPLATES

DEFAULT_TEMPLATE_NAME = "상담일지 (사례관리양식)"

# 기존 사용자 DB에서 제거할 이전 기본 양식의 식별자입니다.
RETIRED_TEMPLATE_KEYS = [
    "SOAP 형식 (표준 임상/차팅)",
    "DAP 형식 (Data-Assessment-Plan)",
    "BIRP 형식 (행동-개입-반응-계획)",
    "일반 상담일지 (복지관 표준)",
    "초기상담 / 인테이크 (신규 접수)",
    "가정방문 모니터링 (재가 안부확인)",
    "전화상담 / 단순 민원 접수",
    "위기개입 / 긴급지원 상담",
    "사례회의 / 통합사례관리 회의록",
    "종결 및 사후관리 기록지",
    "집단 프로그램 / 집단상담 진행일지",
    "민간자원 연계 및 후원 지원 일지",
    "권익옹호 및 권리구제 상담"
]

SYSTEM_PROMPT = """당신은 대한민국 사회복지기관의 전문 사회복지사 및 사례관리 상담기록 전문가입니다.
사용자가 제공하는 상담 메모, 대화 내용, 키워드를 바탕으로 전문적이고 체계적인 [사회복지 상담일지]를 작성하십시오.

[작성 및 출력 지침]
1. 불필요한 서두(예: "네, 상담일지를 작성해 드리겠습니다", "알겠습니다")나 인사말, 맺음말을 절대로 출력하지 마십시오.
2. 첫 줄부터 바로 요청된 서식 제목([상담일지] 등)과 마크다운 본문으로 즉시 시작하십시오.
3. 사회복지 전문 용어와 '강점 관점(Strength Perspective)', '비심판적 태도', '객관적 사실 중심'의 어조를 사용하십시오.
4. 내담자의 개인정보가 마스킹되어 제공된 경우 그대로 유지하십시오.
5. 메모에 언급되지 않은 사실을 허위로 지어내지 말고, 메모된 내용을 논리적이고 정연한 문장으로 정형화하십시오.
"""

TEMPLATES = dict(CASE_FORM_TEMPLATES)


def extract_output_form(guide: str) -> str:
    """AI 작성 지침에서 사람이 직접 채워 쓸 수 있는 출력 양식 부분을 꺼냅니다."""
    marker = "[출력 양식]"
    if marker in guide:
        return guide.split(marker, 1)[1].strip()
    return guide.strip()


def build_prompt(
    template_name: str,
    raw_text: str,
    detail_level: str = "표준",
    guide_override: str = "",
) -> str:
    """
    선택된 양식과 상담 메모, 상세도를 결합하여 LLM 프롬프트를 생성합니다.
    Gemma 2 모델의 Chat 템플릿(<start_of_turn>user ... <end_of_turn><start_of_turn>model) 형식으로 구성합니다.
    """
    template_info = TEMPLATES.get(template_name, TEMPLATES[DEFAULT_TEMPLATE_NAME])
    guide = guide_override.strip() or template_info["guide"]

    detail_instruction = ""
    if detail_level == "간결하게":
        detail_instruction = "\n[주의: 문장을 최대한 핵심 위주로 명료하고 간결하게 압축 작성하십시오.]"
    elif detail_level == "상세하게":
        detail_instruction = "\n[주의: 대상자의 진술과 관찰된 정황, 사정 근거를 매우 구체적이고 상세하게 항목별로 작성하십시오.]"

    user_content = f"""{guide}{detail_instruction}

[입력된 상담 메모]:
{raw_text}

[작성 시작]"""

    # Gemma 2 Chat Template
    formatted_prompt = (
        f"<start_of_turn>user\n"
        f"{SYSTEM_PROMPT}\n\n"
        f"{user_content}<end_of_turn>\n"
        f"<start_of_turn>model\n"
    )

    return formatted_prompt
