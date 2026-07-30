"""01 Empty state 화면의 인사말 + 'Try asking' 칩.

칩 문구는 외국인이 실제로 먼저 묻는 것 위주로 골랐고, 각각이 곧바로 도구를 태우도록 설계했다.
(예: 현금 칩 → cash_and_atm_guide 가 '왜 현금이 필요한지'부터 되묻는 흐름으로 진입)
"""

from .schemas import FaqChip

GREETING = {
    "en": {
        "greeting_title": "Hi there 👋",
        "greeting_subtitle": "How can I help?",
        "greeting_caption": "From luggage storage to directions — just ask.",
        "section_label": "Try asking",
    },
    "ko": {
        "greeting_title": "안녕하세요 👋",
        "greeting_subtitle": "무엇을 도와드릴까요?",
        "greeting_caption": "짐 보관부터 길 안내까지, 편하게 물어보세요.",
        "section_label": "이렇게 물어보세요",
    },
}
GREETING["ja"] = GREETING["en"]
GREETING["zh"] = GREETING["en"]

_CHIPS = {
    "en": [
        FaqChip(id="luggage", icon="🧳", label="Store my luggage",
                prompt="I have a big suitcase. Where can I leave it?"),
        FaqChip(id="deliver", icon="🚚", label="Send bags to my hotel",
                prompt="Can you send my luggage to my hotel so I can go sightseeing?"),
        FaqChip(id="cash", icon="🏧", label="Where can I get cash?",
                prompt="Where can I get cash near here?"),
        FaqChip(id="ticket", icon="🎫", label="Transit card",
                prompt="Can I buy a subway ticket with my foreign credit card?"),
        FaqChip(id="airport", icon="✈️", label="To the airport",
                prompt="I'm heading to Gimhae Airport with two suitcases. What should I do with them?"),
        FaqChip(id="plan", icon="🗺️", label="2-hour plan",
                prompt="I have two hours before check-in and a big suitcase. What should I do?"),
    ],
    "ko": [
        FaqChip(id="luggage", icon="🧳", label="짐 맡길 데 있어?",
                prompt="큰 캐리어가 있는데 어디에 맡길 수 있어?"),
        FaqChip(id="deliver", icon="🚚", label="숙소로 짐 보내기",
                prompt="짐을 숙소로 보내고 구경 다니고 싶어"),
        FaqChip(id="cash", icon="🏧", label="현금 뽑을 곳",
                prompt="이 근처에서 현금 뽑을 수 있는 곳 알려줘"),
        FaqChip(id="ticket", icon="🎫", label="교통카드",
                prompt="지하철 승차권을 카드로 살 수 있어?"),
        FaqChip(id="airport", icon="✈️", label="공항 가는 길",
                prompt="캐리어 2개 들고 김해공항 가려는데 짐은 어떻게 하지?"),
        FaqChip(id="plan", icon="🗺️", label="2시간 계획",
                prompt="체크인까지 2시간 남았고 큰 캐리어가 있어. 뭘 하면 좋을까?"),
    ],
}
_CHIPS["ja"] = _CHIPS["en"]
_CHIPS["zh"] = _CHIPS["en"]


def chips(lang: str) -> list[FaqChip]:
    return _CHIPS.get(lang, _CHIPS["en"])


def greeting(lang: str) -> dict:
    return GREETING.get(lang, GREETING["en"])
