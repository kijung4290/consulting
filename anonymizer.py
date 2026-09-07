"""
사회복지 상담기록 개인정보 비식별화(마스킹) 모듈
- 주민등록번호, 연락처, 이메일, 계좌번호, 상세주소 등 민감한 개인정보를 자동 식별 및 마스킹
"""

import re
from typing import Dict, List, Tuple

class Anonymizer:
    def __init__(self):
        # 1. 주민등록번호 패턴 (13자리: 앞 6자리 - 뒤 7자리, 공백이나 하이픈 허용)
        self.rrn_pattern = re.compile(r'\b(\d{6})[-\s]?([1-4]\d{6})\b')
        
        # 2. 휴대폰 및 유선 전화번호 패턴
        # 한국어 조사("010-1234-5678로")가 바로 붙어도 끝 경계를 놓치지 않도록
        # \b 대신 숫자 기준의 전후방 탐색을 사용합니다.
        self.phone_pattern = re.compile(r'(?<!\d)(01[016789]|02|0[3-9]\d{1})[-\s]?(\d{3,4})[-\s]?(\d{4})(?!\d)')
        
        # 3. 이메일 주소
        self.email_pattern = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
        
        # 4. 은행 계좌번호 패턴 (숫자 10~14자리 사이 하이픈 조합)
        self.account_pattern = re.compile(r'\b\d{3,6}[-\s]\d{2,6}[-\s]\d{3,6}(?:[-\s]\d{1,4})?\b')
        
        # 5. 상세 주소 패턴 (도로명/지번 뒤 호수, 동/호, 번지)
        self.detail_address_pattern = re.compile(r'(\d+동\s*\d+호|\d+호|\d+통\s*\d+반|\d+-\d+번지)')

    def anonymize(self, text: str, client_name: str = "") -> Tuple[str, Dict[str, int]]:
        """
        민감 정보를 비식별화하여 반환하고, 마스킹된 항목별 건수를 카운트합니다.
        """
        stats = {
            "주민번호": 0,
            "연락처": 0,
            "이메일": 0,
            "계좌번호": 0,
            "상세주소": 0,
            "성명": 0
        }
        
        if not text:
            return "", stats

        result = text

        # 1. 대상자 성명 명시적 치환 (입력된 경우)
        if client_name and len(client_name.strip()) >= 2:
            name = client_name.strip()
            # 예: 홍길동 -> 홍OO님
            masked_name = name[0] + "OO님" if len(name) <= 3 else name[0] + "OO" + name[-1] + "님"
            count = len(re.findall(re.escape(name), result))
            if count > 0:
                result = re.sub(re.escape(name), masked_name, result)
                stats["성명"] += count

        # 2. 주민등록번호 마스킹 (예: 800101-1234567 -> 800101-[주민번호 마스킹])
        rrn_matches = self.rrn_pattern.findall(result)
        if rrn_matches:
            stats["주민번호"] += len(rrn_matches)
            result = self.rrn_pattern.sub(r'\1-*******', result)

        # 3. 전화번호 마스킹 (예: 010-1234-5678 -> 010-****-5678 또는 010-****-****)
        phone_matches = self.phone_pattern.findall(result)
        if phone_matches:
            stats["연락처"] += len(phone_matches)
            result = self.phone_pattern.sub(r'\1-****-****', result)

        # 4. 이메일 마스킹 (예: user@example.com -> u***@example.com)
        email_matches = self.email_pattern.findall(result)
        if email_matches:
            stats["이메일"] += len(email_matches)
            result = self.email_pattern.sub('[이메일_마스킹]', result)

        # 5. 계좌번호 마스킹
        account_matches = self.account_pattern.findall(result)
        if account_matches:
            stats["계좌번호"] += len(account_matches)
            result = self.account_pattern.sub('[계좌번호_마스킹]', result)

        # 6. 상세 주소 마스킹 (동/호수/번지 등)
        addr_matches = self.detail_address_pattern.findall(result)
        if addr_matches:
            stats["상세주소"] += len(addr_matches)
            result = self.detail_address_pattern.sub('[상세주소_마스킹]', result)

        return result, stats


if __name__ == "__main__":
    anon = Anonymizer()
    sample = """
    김철수(65세, 590101-1234567) 어르신 전화상담 진행함.
    연락처: 010-9876-5432, 계좌번호: 123-456-789012 (국민은행)
    거주지: 원주시 봉산동 102동 405호
    호소내용: 무릎 관절염으로 거동이 힘들어 식사 해결이 어렵다고 함.
    """
    clean_text, counts = anon.anonymize(sample, client_name="김철수")
    print("비식별화 결과:\n", clean_text)
    print("마스킹 통계:", counts)
